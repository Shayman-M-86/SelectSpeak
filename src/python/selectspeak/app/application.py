import ctypes
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from ..config import DEFAULT_CONFIG, AppConfig
from ..config.settings import SettingsStore
from ..diagnostics import text_preview
from ..input.capture import resolve_capture
from ..input.clipboard import ClipboardService
from ..input.hotkeys import HotkeyManager
from ..input.keymap import to_windows_hotkey
from ..input.ocr_capture import OcrCaptureError, OcrCaptureHotkey
from ..native import shutdown_native_bridge
from ..speech import Speaker, SpeechEvent, SpeechStarted, SpeechTerminal, SpeechWord, TerminalStatus
from ..speech.debug import SpeechDebugEvent
from ..speech.normalization import prepare_for_speech
from ..ui.contracts import Player
from ..ui.hints import shortcut_label
from ..ui.tray import TrayController
from ..ui.winui_bridge import WinUiPlayer, winui_executable
from .playback_session import PlaybackSession
from .voices import VoiceController

logger = logging.getLogger(__name__)


def is_repeat_of_active_speech(*, speaking: bool, active_text: str, captured_text: str) -> bool:
    return speaking and bool(captured_text) and captured_text == active_text


def was_speaking_at(activated_at: float, speech_started_at: float, speech_ended_at: float) -> bool:
    return speech_started_at <= activated_at < speech_ended_at


def should_stop_clipboard_speech_immediately(*, speaking: bool, source: str) -> bool:
    return speaking and source == "clipboard_fallback"


class SelectSpeakApp:
    """Coordinate application state while delegating platform-specific work."""

    def __init__(
        self,
        config: AppConfig = DEFAULT_CONFIG,
        settings: SettingsStore | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._player: Player
        self._state_lock = threading.RLock()
        self._session = PlaybackSession()
        self._clipboard_mode = config.clipboard_mode
        self._auto_hide = config.auto_hide
        self._speech_debug_enabled = config.speech_debug_enabled
        self._last_hotkey_time = 0.0
        self._shutting_down = False
        self._last_request_id = 0
        logger.debug(
            "app.created app_name=%s default_hotkey=%s",
            config.app_name,
            config.default_hotkey,
        )

    def _create_player(self) -> Player:
        """Build the WinUI renderer and start its bridge.

        The executable is required: without it there is nothing to render to,
        and starting headless would leave a process with a global hotkey and no
        way to see or stop what it is doing.
        """
        if winui_executable() is None:
            raise RuntimeError(
                "SelectSpeak's player could not be found. Build it with "
                "build-tools/native/build.ps1, or set SELECTSPEAK_WINUI_EXE."
            )

        player = WinUiPlayer(
            app_name=self._config.app_name,
            hotkey=self._config.default_hotkey,
            ocr_hotkey=self._config.ocr_hotkey,
            auto_hide=self._auto_hide,
            debug_enabled=self._speech_debug_enabled,
            on_play=self.replay,
            on_read=self.read_current,
            on_pause=self.pause,
            on_resume=self.resume,
            on_stop=self.stop,
            on_toggle_playback=self.toggle_playback,
            on_settings=self.open_settings,
            on_toggle_clipboard=self.toggle_clipboard_mode,
            on_toggle_auto_hide=self.toggle_auto_hide,
            on_toggle_debug=self.toggle_speech_debug,
            on_set_hotkey=self.set_hotkey,
            on_set_ocr_hotkey=self.set_ocr_hotkey,
            on_select_voice=self.select_voice,
        )
        player.start()
        logger.info("ui.renderer.started renderer=winui")
        return player

    def open_settings(self) -> None:
        logger.info("ui.settings.requested")
        self._player.open_settings()

    def run(self) -> None:
        logger.info("app.starting")
        try:
            self._enable_dpi_awareness()
            logger.debug("app.creating_services")
            self._player = self._create_player()
            if self._clipboard_mode:
                self._player.set_clipboard_mode(True)
            self._clipboard = ClipboardService()
            self._ocr_capture = OcrCaptureHotkey(
                self._config.ocr_hotkey,
                self._on_ocr_text,
                dll_path=self._config.native_dll,
                language=self._config.ocr_language,
            )
            self._voices = VoiceController(
                self._config,
                self._player,
                debug_callback=self._on_speech_debug,
                on_activated=self._on_voice_activated,
                on_stop_playback=self.stop,
                on_shutdown_requested=self.shutdown,
            )
            self._voices.start()
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
        finally:
            self.shutdown()

    def stop(self) -> None:
        logger.info("playback.stop.requested")
        speaker, text = self._session.stop(self._voices.speaker, time.monotonic())
        speaker.stop()
        self._update_player(speaking=False, text=text)
        logger.info("playback.stopped text=%s", text_preview(text))

    def pause(self) -> None:
        logger.debug("playback.pause.requested")
        state = self._session.snapshot()
        transition = self._session.pause(self._voices.speaker)
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
        transition = self._session.resume(self._voices.speaker)
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

    def toggle_playback(self) -> None:
        """Resolve a single play/pause button press against the current state.

        The WinUI player has one transport button and reports only that it was
        pressed; deciding what that means is Python's job, because only the
        session knows whether it is speaking, paused, or finished.
        """
        state = self._session.snapshot()
        logger.debug(
            "playback.toggle.requested speaking=%s paused=%s",
            state.speaking,
            state.paused,
        )
        if state.speaking and not state.paused:
            self.pause()
        elif state.speaking:
            self.resume()
        else:
            # Nothing is playing, so the button replays the last capture. With
            # no text yet, replay logs and does nothing, which is the right
            # outcome for a press before anything has been read.
            self.replay()

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
        logger.info(
            "capture.mode.changed mode=%s",
            "selection_with_clipboard_fallback" if enabled else "selection_only",
        )

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
        self._voices.select(key)

    def _on_voice_activated(
        self,
        _backend: str,
        _key: str,
        config: AppConfig,
    ) -> None:
        """Make a freshly loaded voice the one that speaks."""
        with self._state_lock:
            if self._shutting_down:
                return
            self._config = config
        self._save_settings(config)

    def shutdown(self) -> None:
        with self._state_lock:
            if self._shutting_down:
                logger.debug("app.shutdown.duplicate_ignored")
                return
            self._shutting_down = True
        logger.info("app.shutdown.started")
        self._cleanup("hotkeys", lambda: getattr(self, "_hotkeys", None) and self._hotkeys.close())
        self._cleanup("ocr", lambda: getattr(self, "_ocr_capture", None) and self._ocr_capture.stop())

        state = self._session.snapshot()
        if state.speaker is not None:
            self._session.stop(state.speaker, time.monotonic(), TerminalStatus.CLOSED)
            self._cleanup("active_playback", state.speaker.stop)

        self._cleanup("voices", lambda: getattr(self, "_voices", None) and self._voices.close())
        self._cleanup("tray", lambda: getattr(self, "_tray", None) and self._tray.stop())
        self._cleanup("player", lambda: getattr(self, "_player", None) and self._player.destroy())
        self._cleanup("native_bridge", shutdown_native_bridge)
        logger.info("app.shutdown.completed")

    @staticmethod
    def _cleanup(name: str, action: Callable[[], object]) -> None:
        try:
            action()
        except Exception:
            logger.exception("app.shutdown.resource_failed resource=%s", name)

    def _on_hotkey(self, selected_text: str, activated_at: float, clipboard_fallback: str = "") -> None:
        if self._shutting_down:
            return
        logger.info("hotkey.activated hotkey=%s", self._hotkeys.hotkey)
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

        requested_mode = "selection_with_clipboard_fallback" if clipboard_mode else "selection_only"
        logger.info(
            "capture.started mode=%s already_speaking=%s speaking_now=%s",
            requested_mode,
            speaking_at_activation,
            speaking_now,
        )
        # Capturing a selection can empty the clipboard to probe for one, so
        # the native layer copies the original text out beforehand. Prefer
        # that snapshot: re-reading the clipboard here would see whatever
        # survived the probe, which is empty when nothing was selected.
        capture = resolve_capture(
            selected_text,
            lambda: clipboard_fallback or self._clipboard.read_text(),
            allow_clipboard_fallback=clipboard_mode,
        )
        if capture.source == "clipboard_fallback":
            logger.info(
                "capture.fallback_to_clipboard selected_length=%d clipboard_length=%d",
                len(selected_text),
                len(capture.raw_text),
            )
        cleaned_text = prepare_for_speech(capture.raw_text)
        logger.info(
            "capture.completed source=%s raw_length=%d cleaned_length=%d raw=%s cleaned=%s",
            capture.source,
            len(capture.raw_text),
            len(cleaned_text),
            text_preview(capture.raw_text),
            text_preview(cleaned_text),
        )
        if not cleaned_text:
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
            captured_text=cleaned_text,
        )
        if stop_repeated_text:
            logger.info(
                "hotkey.repeated_active_text action=stop text_length=%d",
                len(cleaned_text),
            )
            self.stop()
            # The following press should replay immediately, even if it occurs
            # within the ordinary hotkey debounce interval.
            with self._state_lock:
                self._last_hotkey_time = 0.0
            return
        self._begin_speech(cleaned_text, source=capture.source)

    def _on_hotkey_activation(self) -> bool:
        with self._state_lock:
            if self._shutting_down:
                return True
            session = self._session.snapshot()
            stop_clipboard_speech = should_stop_clipboard_speech_immediately(
                speaking=session.speaking, source=session.source
            )
        if self._voices.switching:
            activity = self._voices.activity
            logger.info("hotkey.ignored_backend_%s", activity)
            self._player.call_soon(lambda: self._player.show_backend_loading(activity))
            return True
        if stop_clipboard_speech:
            logger.info("hotkey.clipboard_speech.immediate_stop")
            self.stop()
            with self._state_lock:
                self._last_hotkey_time = 0.0
            return True
        return False

    def _begin_speech(self, text: str, *, source: str = "replay") -> None:
        if self._shutting_down:
            logger.debug("speech.ignored_app_closing")
            return
        if self._voices.switching:
            activity = self._voices.activity
            logger.info("speech.ignored_backend_%s", activity)
            self._player.call_soon(lambda: self._player.show_backend_loading(activity))
            return
        logger.info(
            "speech.queue.requested text_length=%d text=%s",
            len(text),
            text_preview(text),
        )
        speaker = self._voices.speaker
        self._player.call_soon(self._player.reset_speech_debug)
        with self._state_lock:
            if self._last_request_id == (1 << 64) - 1:
                logger.error("speech.queue.rejected request_id_exhausted")
                return
            self._last_request_id += 1
            request_id = self._last_request_id
        try:
            accepted = speaker.speak(
                request_id,
                text,
                lambda event: self._on_speech_event(speaker, text, source, event),
            )
        except RuntimeError:
            logger.exception("speech.queue.failed")
            return
        if not accepted:
            logger.warning(
                "speech.queue.rejected request_id=%d text_length=%d minimum_length=%d",
                request_id,
                len(text),
                self._config.minimum_text_length,
            )
            return
        logger.info("speech.queued request_id=%d text_length=%d", request_id, len(text))

    def _on_speech_event(
        self,
        speaker: Speaker,
        text: str,
        source: str,
        event: SpeechEvent,
    ) -> None:
        if isinstance(event, SpeechStarted):
            with self._state_lock:
                stale = event.request_id != self._last_request_id
                shutting_down = self._shutting_down
            if shutting_down or stale:
                logger.debug("speech.started.stale request_id=%d", event.request_id)
                return
            self._session.start(speaker, event.request_id, text, source, time.monotonic())
            self._update_player(speaking=True, text=text)
            logger.info("speech.started request_id=%d", event.request_id)
            return
        if isinstance(event, SpeechWord):
            state = self._session.snapshot()
            if self._shutting_down or state.request_id != event.request_id:
                return
            logger.debug(
                "speech.word_boundary request_id=%d position=%d length=%d",
                event.request_id,
                event.position,
                event.length,
            )
            self._player.call_soon(
                lambda position=event.position, length=event.length: self._player.highlight_word(
                    position,
                    length,
                )
            )
            return
        if not isinstance(event, SpeechTerminal):
            raise TypeError(f"Unknown speech event: {type(event).__name__}")
        if not self._session.complete(
            speaker,
            event.request_id,
            event.status,
            time.monotonic(),
        ):
            logger.debug(
                "speech.terminal.stale request_id=%d status=%s",
                event.request_id,
                event.status.name.casefold(),
            )
            return
        if not self._shutting_down:
            self._update_player(speaking=False, text=text)
        logger.info(
            "speech.terminal request_id=%d status=%s",
            event.request_id,
            event.status.name.casefold(),
        )

    def _update_player(self, *, speaking: bool, paused: bool = False, text: str = "") -> None:
        logger.debug(
            "ui.playback_update.queued speaking=%s paused=%s text_length=%d",
            speaking,
            paused,
            len(text),
        )
        self._player.call_soon(lambda: self._player.set_playback(speaking=speaking, paused=paused, text=text))

    def _on_speech_debug(self, event: SpeechDebugEvent) -> None:
        if self._shutting_down:
            return
        self._player.call_soon(lambda event=event: self._player.update_speech_debug(event))

    def _on_ocr_text(self, captured_text: str) -> None:
        if self._shutting_down:
            return
        text = prepare_for_speech(captured_text)
        logger.info(
            "ocr_capture.text_prepared raw_length=%d cleaned_length=%d text=%s",
            len(captured_text),
            len(text),
            text_preview(text),
        )
        if text:
            self._begin_speech(text, source="ocr")

    def set_hotkey(self, hotkey: str) -> None:
        """Bind the shortcut the user confirmed in the settings dialog.

        The keys came from our own recorder, but they arrive back over the
        pipe, so the string is validated here before anything is bound; a
        rejected one leaves the existing binding alone.
        """
        logger.info("hotkey.set.requested hotkey=%s", hotkey)
        try:
            to_windows_hotkey(hotkey)
        except ValueError:
            logger.warning("hotkey.set.rejected hotkey=%s", hotkey)
            self._reject_hotkey(f"{shortcut_label(hotkey)} is not a shortcut that can be bound.")
            return
        self._apply_hotkey(hotkey)

    def _apply_hotkey(self, hotkey: str) -> None:
        logger.info("hotkey.rebind.requested hotkey=%s", hotkey)
        try:
            self._hotkeys.rebind(hotkey)
        except Exception:
            logger.exception("hotkey.rebind.failed hotkey=%s", hotkey)
            self._reject_hotkey(f"{shortcut_label(hotkey)} is already in use by another application.")
            return
        self._tray.update_hotkey(hotkey)
        with self._state_lock:
            self._config = replace(self._config, default_hotkey=hotkey)
            config = self._config
        self._save_settings(config)
        logger.info("hotkey.rebind.completed hotkey=%s", hotkey)

    def set_ocr_hotkey(self, hotkey: str) -> None:
        """Bind the capture shortcut the user confirmed in the settings dialog.

        The read shortcut's counterpart: same validation, same rejection
        behaviour, so a bad combination leaves the existing binding alone.
        """
        logger.info("ocr_hotkey.set.requested hotkey=%s", hotkey)
        try:
            to_windows_hotkey(hotkey)
        except ValueError:
            logger.warning("ocr_hotkey.set.rejected hotkey=%s", hotkey)
            self._reject_hotkey(
                f"{shortcut_label(hotkey)} is not a shortcut that can be bound.",
                ocr=True,
            )
            return
        self._apply_ocr_hotkey(hotkey)

    def _apply_ocr_hotkey(self, hotkey: str) -> None:
        logger.info("ocr_hotkey.rebind.requested hotkey=%s", hotkey)
        if self._ocr_capture is None:
            logger.warning("ocr_hotkey.rebind.unavailable hotkey=%s", hotkey)
            self._reject_hotkey(
                "Screen capture is unavailable, so its shortcut cannot be changed.",
                ocr=True,
            )
            return
        try:
            self._ocr_capture.rebind(hotkey)
        except Exception:
            logger.exception("ocr_hotkey.rebind.failed hotkey=%s", hotkey)
            # The previous shortcut is still bound, so report that rather than
            # leaving the settings window showing one that was never taken.
            self._reject_hotkey(
                f"{shortcut_label(hotkey)} is already in use by another application.",
                ocr=True,
            )
            return
        self._player.set_ocr_hotkey(hotkey)
        with self._state_lock:
            self._config = replace(self._config, ocr_hotkey=hotkey)
            config = self._config
        self._save_settings(config)
        logger.info("ocr_hotkey.rebind.completed hotkey=%s", hotkey)

    def _reject_hotkey(self, message: str, *, ocr: bool = False) -> None:
        """Explain a shortcut that would not bind, and restore the one in use.

        Both shortcuts revert to their current binding on failure, so the row
        is put back first and the reason shown second; without the message the
        settings window just snaps back and looks broken.
        """
        if ocr:
            self._player.set_ocr_hotkey(self._config.ocr_hotkey)
        else:
            self._player.set_hotkey(self._hotkeys.hotkey)
        self._player.show_hotkey_error(message)

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
