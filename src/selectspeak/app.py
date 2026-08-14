import ctypes
import logging
import threading
import time
from dataclasses import replace

from .config import DEFAULT_CONFIG, AppConfig
from .input.capture import resolve_capture
from .input.clipboard import ClipboardService
from .input.hotkeys import HotkeyManager
from .input.ocr_capture import OcrCaptureError, OcrCaptureHotkey
from .logging_setup import text_preview
from .native import shutdown_native_bridge
from .playback_session import PlaybackSession
from .settings import SettingsStore
from .speech import Speaker, create_speaker
from .speech.backends.natural import NaturalVoiceSpeaker, discover_natural_voices
from .speech.debug import SpeechDebugEvent
from .speech.feature_installer import launch_supertonic_installer
from .speech.model_installation import supertonic_model_is_installed
from .speech.normalization import prepare_for_speech
from .speech.optional_dependencies import supertonic_dependencies_are_installed
from .speech.voices import VoiceOption, build_voice_options, natural_voice_key
from .ui.player import PlayerWindow
from .ui.tray import TrayController

logger = logging.getLogger(__name__)

BACKEND_INSTALLING = "installing"
BACKEND_LOADING = "loading"
MESSAGE_BOX_YES_NO = 0x00000004
MESSAGE_BOX_ICON_QUESTION = 0x00000020
MESSAGE_BOX_YES = 6


def is_repeat_of_active_speech(*, speaking: bool, active_text: str, captured_text: str) -> bool:
    return speaking and bool(captured_text) and captured_text == active_text


def was_speaking_at(activated_at: float, speech_started_at: float, speech_ended_at: float) -> bool:
    return speech_started_at <= activated_at < speech_ended_at


def should_stop_clipboard_speech_immediately(*, speaking: bool, source: str) -> bool:
    return speaking and source in {"clipboard", "clipboard_fallback"}


def confirm_supertonic_install() -> bool:
    """Ask before handing control to setup for the large optional component."""
    windows_libraries = getattr(ctypes, "windll", None)
    if windows_libraries is None:
        return False
    result = windows_libraries.user32.MessageBoxW(
        None,
        "Supertonic Neural Voice is not installed.\n\n"
        "Setup will add its Python dependencies and local voice model, requiring "
        "approximately 475 MB. SelectSpeak will restart when setup finishes.\n\n"
        "Install Supertonic now?",
        "Install Supertonic Neural Voice",
        MESSAGE_BOX_YES_NO | MESSAGE_BOX_ICON_QUESTION,
    )
    return result == MESSAGE_BOX_YES


class SelectSpeakApp:
    """Coordinate application state while delegating platform-specific work."""

    def __init__(
        self,
        config: AppConfig = DEFAULT_CONFIG,
        settings: SettingsStore | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._state_lock = threading.RLock()
        self._session = PlaybackSession()
        self._clipboard_mode = config.clipboard_mode
        self._auto_hide = config.auto_hide
        self._speech_debug_enabled = config.speech_debug_enabled
        self._speech_backend = "supertonic" if config.speech_backend.casefold() == "supertonic" else "windows"
        self._backend_switching = False
        self._backend_activity = ""
        self._last_hotkey_time = 0.0
        self._shutting_down = False
        logger.debug(
            "app.created app_name=%s default_hotkey=%s",
            config.app_name,
            config.default_hotkey,
        )

    def run(self) -> None:
        logger.info("app.starting")
        self._enable_dpi_awareness()
        logger.debug("app.creating_services")
        self._player = PlayerWindow(
            app_name=self._config.app_name,
            hotkey=self._config.default_hotkey,
            ocr_hotkey=self._config.ocr_hotkey,
            on_play=self.replay,
            on_read=self.read_current,
            on_pause=self.pause,
            on_resume=self.resume,
            on_stop=self.stop,
            on_refresh_voices=self.refresh_voice_options,
            on_select_voice=self.select_voice,
            on_toggle_clipboard=self.toggle_clipboard_mode,
            on_toggle_auto_hide=self.toggle_auto_hide,
            on_toggle_debug=self.toggle_speech_debug,
            on_capture_hotkey=self.start_hotkey_capture,
            auto_hide=self._auto_hide,
            speech_backend=self._speech_backend,
            debug_enabled=self._speech_debug_enabled,
        )
        if self._clipboard_mode:
            self._player.set_clipboard_mode(True)
        self._clipboard = ClipboardService()
        self._ocr_capture = OcrCaptureHotkey(
            self._config.ocr_hotkey,
            self._on_ocr_text,
            dll_path=self._config.native_dll,
            language=self._config.ocr_language,
        )
        self._speaker = create_speaker(self._config, self._on_word, self._on_speech_debug)
        self._speech_backend = self._speaker_backend(self._speaker)
        self._speakers = {self._speech_backend: self._speaker}
        self._configure_voice_options()
        self._hotkeys = HotkeyManager(
            self._config.default_hotkey,
            self._on_hotkey,
            self._on_hotkey_activation,
            native_dll=self._config.native_dll,
        )
        self._tray = TrayController(
            app_name=self._config.app_name,
            hotkey=self._config.default_hotkey,
            on_show=lambda: self._player.call_soon(self._player.show),
            on_quit=lambda: self._player.call_soon(self.shutdown),
        )

        self._hotkeys.register()
        try:
            self._ocr_capture.start()
        except OcrCaptureError:
            logger.exception("ocr_hotkey.registration_failed hotkey=%s", self._config.ocr_hotkey)
        self._tray.start()
        logger.info(
            "app.started hotkey=%s clipboard_mode=%s",
            self._hotkeys.hotkey,
            self._clipboard_mode,
        )
        logger.debug("ui.mainloop.entering")
        self._player.mainloop()
        logger.info("ui.mainloop.exited")

    def stop(self) -> None:
        logger.info("playback.stop.requested")
        speaker, text = self._session.stop(self._speaker, time.monotonic())
        speaker.stop()
        self._update_player(speaking=False, text=text)
        logger.info("playback.stopped text=%s", text_preview(text))

    def pause(self) -> None:
        logger.debug("playback.pause.requested")
        state = self._session.snapshot()
        transition = self._session.pause(self._speaker)
        if transition is None:
            logger.debug(
                "playback.pause.ignored speaking=%s paused=%s",
                state.speaking,
                state.paused,
            )
            return
        speaker, text = transition
        speaker.pause()
        self._update_player(speaking=True, paused=True, text=text)
        logger.info("playback.paused")

    def resume(self) -> None:
        logger.debug("playback.resume.requested")
        state = self._session.snapshot()
        transition = self._session.resume(self._speaker)
        if transition is None:
            logger.debug(
                "playback.resume.ignored speaking=%s paused=%s",
                state.speaking,
                state.paused,
            )
            return
        speaker, text = transition
        speaker.resume()
        self._update_player(speaking=True, paused=False, text=text)
        logger.info("playback.resumed")

    def replay(self) -> None:
        logger.info("playback.replay.requested")
        state = self._session.snapshot()
        text = state.text
        source = state.source or "replay"
        if text:
            self._begin_speech(text, source=source)
        else:
            logger.debug("playback.replay.ignored_no_text")

    def read_current(self) -> None:
        """Run the same native capture used by the global hotkey."""
        logger.info("capture.button.requested")
        self._trigger_button_capture()

    def _trigger_button_capture(self) -> None:
        try:
            self._hotkeys.trigger()
        except Exception:
            logger.exception("capture.button.failed")
            self._player.show()

    def toggle_clipboard_mode(self) -> None:
        with self._state_lock:
            self._clipboard_mode = not self._clipboard_mode
            enabled = self._clipboard_mode
            self._config = replace(self._config, clipboard_mode=enabled)
            config = self._config
        self._player.set_clipboard_mode(enabled)
        self._save_settings(config)
        logger.info("capture.mode.changed mode=%s", "clipboard" if enabled else "auto")

    def toggle_auto_hide(self) -> None:
        with self._state_lock:
            self._auto_hide = not self._auto_hide
            enabled = self._auto_hide
            self._config = replace(self._config, auto_hide=enabled)
            config = self._config
        self._player.set_auto_hide(enabled)
        self._save_settings(config)
        logger.info("player.auto_hide.changed enabled=%s", enabled)

    def toggle_speech_debug(self) -> None:
        with self._state_lock:
            self._speech_debug_enabled = not self._speech_debug_enabled
            enabled = self._speech_debug_enabled
            self._config = replace(self._config, speech_debug_enabled=enabled)
            config = self._config
        self._player.set_debug_enabled(enabled)
        self._save_settings(config)
        logger.info("speech.debug.changed enabled=%s", enabled)

    def select_voice(self, key: str) -> None:
        option = self._voice_options.get(key)
        if option is None:
            return
        if option.backend == "supertonic" and self._supertonic_install_required():
            self._request_supertonic_install(option)
            return
        activity = self._voice_load_activity(option)
        with self._state_lock:
            if self._backend_switching:
                return
            if key == self._selected_voice_key:
                return
            self._backend_switching = True
            self._backend_activity = activity
            current_key = self._selected_voice_key
        self.stop()

        def show_activity() -> None:
            self._player.set_voice_selection(option.key, option.short_label, activity=activity)
            self._player.show_backend_loading(activity)

        # stop() queues an idle playback update. Queue this after it so the
        # loading state remains visible instead of being immediately hidden.
        self._player.call_soon(show_activity)
        threading.Thread(
            target=self._load_voice,
            args=(current_key, option),
            daemon=True,
            name=f"VoiceSelection-{option.backend}",
        ).start()

    def _request_supertonic_install(self, option: VoiceOption) -> None:
        current_key = self._selected_voice_key
        if not confirm_supertonic_install():
            current = self._voice_options[current_key]
            self._player.set_voice_selection(current.key, current.short_label)
            return
        with self._state_lock:
            if self._backend_switching:
                return
            self._backend_switching = True
            self._backend_activity = BACKEND_INSTALLING
        self.stop()
        self._player.call_soon(
            lambda: self._player.set_voice_selection(
                option.key,
                option.short_label,
                activity=BACKEND_INSTALLING,
            )
        )
        self._player.call_soon(lambda: self._player.show_backend_loading(BACKEND_INSTALLING))
        threading.Thread(
            target=self._launch_supertonic_setup,
            args=(current_key,),
            daemon=True,
            name="SupertonicSetup",
        ).start()

    def _launch_supertonic_setup(self, current_key: str) -> None:
        try:
            launch_supertonic_installer()
        except Exception as error:
            logger.exception("supertonic.setup.launch_failed")
            current = self._voice_options[current_key]
            self._player.call_soon(
                lambda: self._player.set_voice_selection(current.key, current.short_label)
            )
            self._player.call_soon(
                lambda message=str(error): self._player.show_backend_error(message)
            )
            with self._state_lock:
                self._backend_switching = False
                self._backend_activity = ""
            return
        logger.info("supertonic.setup.launched")
        self._player.call_soon(self.shutdown)

    def _load_voice(self, current_key: str, option: VoiceOption) -> None:
        try:
            speaker = self._speakers.get(option.backend)
            selected_config = replace(
                self._config,
                speech_backend=option.backend,
                preferred_voice_match=(
                    option.package_path if option.backend == "natural" else self._config.preferred_voice_match
                ),
            )
            if option.backend == "natural" and isinstance(speaker, NaturalVoiceSpeaker):
                speaker.select_voice(option.package_path)
            elif speaker is None:
                speaker = create_speaker(selected_config, self._on_word, self._on_speech_debug)
                self._speakers[option.backend] = speaker
            with self._state_lock:
                if self._shutting_down:
                    return
                self._speaker = speaker
                self._speech_backend = option.backend
                self._selected_voice_key = option.key
                self._config = selected_config
            self._save_settings(selected_config)

            def show_ready() -> None:
                self._player.set_voice_selection(option.key, option.short_label)
                self._player.show_backend_ready(option.short_label)

            self._player.call_soon(show_ready)
            logger.info(
                "speaker.voice.changed backend=%s key=%s label=%s",
                option.backend,
                option.key,
                option.label,
            )
        except Exception as error:
            logger.exception(
                "speaker.voice.change_failed backend=%s key=%s",
                option.backend,
                option.key,
            )
            current = self._voice_options[current_key]
            self._player.call_soon(lambda: self._player.set_voice_selection(current.key, current.short_label))
            self._player.call_soon(lambda message=str(error): self._player.show_backend_error(message))
        finally:
            with self._state_lock:
                self._backend_switching = False
                self._backend_activity = ""

    def _voice_load_activity(self, option: VoiceOption) -> str:
        if option.backend != "supertonic":
            return BACKEND_LOADING
        return BACKEND_INSTALLING if self._supertonic_install_required() else BACKEND_LOADING

    def _supertonic_install_required(self) -> bool:
        try:
            return not (
                supertonic_dependencies_are_installed()
                and supertonic_model_is_installed(self._config.supertonic_voice)
            )
        except Exception:
            logger.exception("supertonic.installation_state_failed")
            return True

    def _configure_voice_options(self) -> None:
        try:
            if isinstance(self._speaker, NaturalVoiceSpeaker):
                natural_voices = list(self._speaker.available_voices)
            else:
                natural_voices = discover_natural_voices(self._config.speech)
        except Exception:
            logger.exception("speaker.voice.discovery_failed")
            natural_voices = []

        options = build_voice_options(natural_voices, self._config.speech)
        self._voice_options = {option.key: option for option in options}
        if isinstance(self._speaker, NaturalVoiceSpeaker):
            selected_key = natural_voice_key(self._speaker.voice.package_path)
        elif self._speech_backend == "supertonic":
            selected_key = "supertonic"
        else:
            selected_key = "sapi"
        self._selected_voice_key = selected_key
        self._player.set_voice_options(options, selected_key)

    def refresh_voice_options(self) -> None:
        """Re-enumerate voice packages immediately before opening the menu."""
        with self._state_lock:
            if self._backend_switching or self._shutting_down:
                return
            selected_key = self._selected_voice_key
            natural_speaker = self._speakers.get("natural")
        try:
            if isinstance(natural_speaker, NaturalVoiceSpeaker):
                natural_voices = list(natural_speaker.refresh_voices())
            else:
                natural_voices = discover_natural_voices(self._config.speech)
        except Exception:
            logger.exception("speaker.voice.refresh_failed")
            return

        options = build_voice_options(natural_voices, self._config.speech)
        with self._state_lock:
            self._voice_options = {option.key: option for option in options}
        self._player.set_voice_options(options, selected_key)
        logger.info("speaker.voices.refreshed count=%d", len(natural_voices))

    @staticmethod
    def _speaker_backend(speaker: Speaker) -> str:
        if isinstance(speaker, NaturalVoiceSpeaker):
            return "natural"
        name = type(speaker).__name__.casefold()
        return "supertonic" if "supertonic" in name else "sapi"

    def start_hotkey_capture(self) -> None:
        logger.info("hotkey.capture.requested")
        if self._session.snapshot().speaking:
            logger.info("hotkey.capture.ignored_while_speaking")
            return
        started = self._hotkeys.start_capture(
            timeout_seconds=self._config.capture_timeout_seconds,
            on_preview=lambda combo: self._player.call_soon(lambda: self._player.show_capture_preview(combo)),
            on_complete=lambda combo: self._player.call_soon(lambda: self._apply_hotkey(combo)),
            on_cancel=lambda: self._player.call_soon(self._cancel_hotkey_capture),
        )
        if started:
            self._player.show_capture_started()
            logger.info("hotkey.capture.started")
        else:
            logger.debug("hotkey.capture.already_active")

    def shutdown(self) -> None:
        if self._shutting_down:
            logger.debug("app.shutdown.duplicate_ignored")
            return
        logger.info("app.shutdown.started")
        self._shutting_down = True
        for speaker in self._speakers.values():
            speaker.stop()
        self._ocr_capture.stop()
        self._hotkeys.close()
        shutdown_native_bridge()
        self._tray.stop()
        self._player.destroy()
        logger.info("app.shutdown.completed")

    def _on_hotkey(self, selected_text: str, activated_at: float) -> None:
        logger.info("hotkey.activated hotkey=%s", self._hotkeys.hotkey)
        if self._hotkeys.capturing:
            logger.debug("hotkey.ignored_during_capture")
            return
        now = activated_at
        with self._state_lock:
            elapsed = now - self._last_hotkey_time
            if elapsed < self._config.hotkey_debounce_seconds:
                logger.debug("hotkey.debounced elapsed=%.4fs", elapsed)
                return
            self._last_hotkey_time = now
            clipboard_mode = self._clipboard_mode
            session = self._session.snapshot()
            speaking_now = session.speaking
            speaking_at_activation = was_speaking_at(activated_at, session.started_at, session.ended_at)

        requested_mode = "clipboard" if clipboard_mode else "auto"
        logger.info(
            "capture.started mode=%s already_speaking=%s speaking_now=%s",
            requested_mode,
            speaking_at_activation,
            speaking_now,
        )
        capture = resolve_capture(selected_text, self._clipboard.read_text, force_clipboard=clipboard_mode)
        if capture.source == "clipboard_fallback":
            logger.info(
                "capture.fallback_to_clipboard selected_length=%d clipboard_length=%d",
                len(selected_text),
                len(capture.raw_text),
            )
        logger.info(
            "capture.completed source=%s raw_length=%d cleaned_length=%d raw=%s cleaned=%s",
            capture.source,
            len(capture.raw_text),
            len(capture.text),
            text_preview(capture.raw_text),
            text_preview(capture.text),
        )
        if not capture.text:
            logger.warning(
                "capture.empty source=%s action=%s",
                capture.source,
                "stop" if speaking_at_activation else "show_player",
            )
            if speaking_at_activation:
                self.stop()
            else:
                self._player.call_soon(self._player.show)
            return
        stop_repeated_text = is_repeat_of_active_speech(
            speaking=speaking_at_activation,
            active_text=self._session.snapshot().text,
            captured_text=capture.text,
        )
        if stop_repeated_text:
            logger.info(
                "hotkey.repeated_active_text action=stop text_length=%d",
                len(capture.text),
            )
            self.stop()
            # The following press should replay immediately, even if it occurs
            # within the ordinary hotkey debounce interval.
            with self._state_lock:
                self._last_hotkey_time = 0.0
            return
        self._begin_speech(capture.text, source=capture.source)

    def _on_hotkey_activation(self) -> bool:
        with self._state_lock:
            backend_switching = self._backend_switching
            backend_activity = self._backend_activity
            clipboard_mode = self._clipboard_mode
            session = self._session.snapshot()
            stop_clipboard_speech = should_stop_clipboard_speech_immediately(
                speaking=session.speaking, source=session.source
            )
        if backend_switching:
            logger.info("hotkey.ignored_backend_%s", backend_activity or BACKEND_LOADING)
            self._player.call_soon(
                lambda: self._player.show_backend_loading(backend_activity or BACKEND_LOADING)
            )
            return True
        if stop_clipboard_speech:
            logger.info("hotkey.clipboard_speech.immediate_stop")
            self.stop()
            with self._state_lock:
                self._last_hotkey_time = 0.0
            return True
        if clipboard_mode:
            logger.debug("hotkey.clipboard_mode.direct_capture")
            self._on_hotkey("", time.monotonic())
            return True
        return False

    def _begin_speech(self, text: str, *, source: str = "replay") -> None:
        with self._state_lock:
            if self._backend_switching:
                activity = self._backend_activity or BACKEND_LOADING
                logger.info("speech.ignored_backend_%s", activity)
                self._player.call_soon(lambda: self._player.show_backend_loading(activity))
                return
        logger.info(
            "speech.queue.requested text_length=%d text=%s",
            len(text),
            text_preview(text),
        )
        speaker = self._speaker
        self._player.call_soon(self._player.reset_speech_debug)
        try:
            generation = speaker.speak(text)
        except RuntimeError:
            logger.exception("speech.queue.failed")
            return
        if generation is None:
            logger.warning(
                "speech.queue.rejected text_length=%d minimum_length=%d",
                len(text),
                self._config.minimum_text_length,
            )
            return
        self._session.start(speaker, generation, text, source, time.monotonic())
        self._update_player(speaking=True, text=text)
        logger.info("speech.queued generation=%d text_length=%d", generation, len(text))
        threading.Thread(
            target=self._wait_for_speech,
            args=(speaker, generation, text),
            daemon=True,
            name=f"SpeechWait-{generation}",
        ).start()

    def _wait_for_speech(self, speaker: Speaker, generation: int, text: str) -> None:
        logger.debug("speech.wait.started generation=%d", generation)
        if not speaker.wait_until_done(generation):
            logger.info("speech.wait.superseded generation=%d", generation)
            return
        if not self._session.complete(speaker, generation, time.monotonic()):
            logger.debug("speech.completion.stale generation=%d", generation)
            return
        self._update_player(speaking=False, text=text)
        logger.info("speech.completed generation=%d", generation)

    def _update_player(self, *, speaking: bool, paused: bool = False, text: str = "") -> None:
        logger.debug(
            "ui.playback_update.queued speaking=%s paused=%s text_length=%d",
            speaking,
            paused,
            len(text),
        )
        self._player.call_soon(lambda: self._player.set_playback(speaking=speaking, paused=paused, text=text))

    def _on_word(self, _text: str, position: int, length: int) -> None:
        logger.debug("speech.word_boundary position=%d length=%d", position, length)
        self._player.highlight_word(position, length)

    def _on_speech_debug(self, event: SpeechDebugEvent) -> None:
        self._player.call_soon(lambda event=event: self._player.update_speech_debug(event))

    def _on_ocr_text(self, captured_text: str) -> None:
        text = prepare_for_speech(captured_text)
        logger.info(
            "ocr_capture.text_prepared raw_length=%d cleaned_length=%d text=%s",
            len(captured_text),
            len(text),
            text_preview(text),
        )
        if text:
            self._begin_speech(text, source="ocr")

    def _apply_hotkey(self, hotkey: str) -> None:
        logger.info("hotkey.rebind.requested hotkey=%s", hotkey)
        try:
            self._hotkeys.rebind(hotkey)
        except Exception:
            logger.exception("hotkey.rebind.failed hotkey=%s", hotkey)
            self._player.show_idle_hint()
            return
        self._player.show_capture_complete(hotkey)
        self._tray.update_hotkey(hotkey)
        with self._state_lock:
            self._config = replace(self._config, default_hotkey=hotkey)
            config = self._config
        self._save_settings(config)
        logger.info("hotkey.rebind.completed hotkey=%s", hotkey)

    def _cancel_hotkey_capture(self) -> None:
        logger.info("hotkey.capture.cancelled")
        self._player.set_hotkey(self._hotkeys.hotkey)
        self._player.show_idle_hint()

    def _save_settings(self, config: AppConfig) -> None:
        if self._settings is None:
            return
        try:
            self._settings.save(config)
        except Exception:
            logger.exception("settings.save_failed path=%s", self._settings.path)

    @staticmethod
    def _enable_dpi_awareness() -> None:
        try:
            windows_libraries = getattr(ctypes, "windll", None)
            if windows_libraries is not None:
                # Per-monitor v2 keeps Tk's measured layout and the native window
                # size in agreement when displays use different scale factors.
                enabled = windows_libraries.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
                if enabled:
                    logger.debug("dpi_awareness.enabled mode=per_monitor_v2")
                else:
                    windows_libraries.shcore.SetProcessDpiAwareness(1)
                    logger.debug("dpi_awareness.enabled mode=system")
            else:
                logger.debug("dpi_awareness.unavailable")
        except Exception:
            logger.exception("dpi_awareness.failed")


def main(
    config: AppConfig = DEFAULT_CONFIG,
    settings: SettingsStore | None = None,
) -> None:
    SelectSpeakApp(config, settings).run()
