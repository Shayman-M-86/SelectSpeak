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
from .logging_setup import log_event, log_exception, text_preview
from .playback_session import PlaybackSession
from .speech import Speaker, create_speaker
from .speech.debug import SpeechDebugEvent
from .speech.normalization import prepare_for_speech
from .ui.player import PlayerWindow
from .ui.tray import TrayController

logger = logging.getLogger(__name__)


def is_repeat_of_active_speech(
    *, speaking: bool, active_text: str, captured_text: str
) -> bool:
    return speaking and bool(captured_text) and captured_text == active_text


def was_speaking_at(
    activated_at: float, speech_started_at: float, speech_ended_at: float
) -> bool:
    return speech_started_at <= activated_at < speech_ended_at


def should_stop_clipboard_speech_immediately(*, speaking: bool, source: str) -> bool:
    return speaking and source in {"clipboard", "clipboard_fallback"}


class SelectSpeakApp:
    """Coordinate application state while delegating platform-specific work."""

    def __init__(self, config: AppConfig = DEFAULT_CONFIG) -> None:
        self._config = config
        self._state_lock = threading.RLock()
        self._session = PlaybackSession()
        self._clipboard_mode = False
        self._auto_hide = config.auto_hide
        self._speech_debug_enabled = config.speech_debug_enabled
        self._speech_backend = (
            "supertonic"
            if config.speech_backend.casefold() == "supertonic"
            else "windows"
        )
        self._windows_speech_backend = (
            config.speech_backend
            if config.speech_backend.casefold() in {"auto", "natural", "sapi"}
            else "auto"
        )
        self._backend_switching = False
        self._last_hotkey_time = 0.0
        self._shutting_down = False
        log_event(
            logger,
            logging.DEBUG,
            "app.created",
            app_name=config.app_name,
            default_hotkey=config.default_hotkey,
        )

    def run(self) -> None:
        log_event(logger, logging.INFO, "app.starting")
        self._enable_dpi_awareness()
        log_event(logger, logging.DEBUG, "app.creating_services")
        self._player = PlayerWindow(
            app_name=self._config.app_name,
            hotkey=self._config.default_hotkey,
            ocr_hotkey=self._config.ocr_hotkey,
            on_play=self.replay,
            on_read=self.read_current,
            on_pause=self.pause,
            on_resume=self.resume,
            on_stop=self.stop,
            on_toggle_speech_backend=self.toggle_speech_backend,
            on_toggle_clipboard=self.toggle_clipboard_mode,
            on_toggle_auto_hide=self.toggle_auto_hide,
            on_toggle_debug=self.toggle_speech_debug,
            on_capture_hotkey=self.start_hotkey_capture,
            auto_hide=self._auto_hide,
            speech_backend=self._speech_backend,
            debug_enabled=self._speech_debug_enabled,
        )
        self._clipboard = ClipboardService()
        self._ocr_capture = OcrCaptureHotkey(
            self._config.ocr_hotkey,
            self._on_ocr_text,
            dll_path=self._config.native_input_dll,
            language=self._config.ocr_language,
        )
        self._speaker = create_speaker(
            self._config, self._on_word, self._on_speech_debug
        )
        self._speakers = {self._speech_backend: self._speaker}
        self._hotkeys = HotkeyManager(
            self._config.default_hotkey,
            self._on_hotkey,
            self._on_hotkey_activation,
            native_dll=self._config.native_input_dll,
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
            log_exception(
                logger,
                "ocr_hotkey.registration_failed",
                hotkey=self._config.ocr_hotkey,
            )
        self._tray.start()
        log_event(
            logger,
            logging.INFO,
            "app.started",
            hotkey=self._hotkeys.hotkey,
            clipboard_mode=self._clipboard_mode,
        )
        log_event(logger, logging.DEBUG, "ui.mainloop.entering")
        self._player.mainloop()
        log_event(logger, logging.INFO, "ui.mainloop.exited")

    def stop(self) -> None:
        log_event(logger, logging.INFO, "playback.stop.requested")
        speaker, text = self._session.stop(self._speaker, time.monotonic())
        speaker.stop()
        self._update_player(speaking=False, text=text)
        log_event(
            logger,
            logging.INFO,
            "playback.stopped",
            last_text_preview=text_preview(text),
        )

    def pause(self) -> None:
        log_event(logger, logging.DEBUG, "playback.pause.requested")
        state = self._session.snapshot()
        transition = self._session.pause(self._speaker)
        if transition is None:
            log_event(
                logger,
                logging.DEBUG,
                "playback.pause.ignored",
                speaking=state.speaking,
                paused=state.paused,
            )
            return
        speaker, text = transition
        speaker.pause()
        self._update_player(speaking=True, paused=True, text=text)
        log_event(logger, logging.INFO, "playback.paused")

    def resume(self) -> None:
        log_event(logger, logging.DEBUG, "playback.resume.requested")
        state = self._session.snapshot()
        transition = self._session.resume(self._speaker)
        if transition is None:
            log_event(
                logger,
                logging.DEBUG,
                "playback.resume.ignored",
                speaking=state.speaking,
                paused=state.paused,
            )
            return
        speaker, text = transition
        speaker.resume()
        self._update_player(speaking=True, paused=False, text=text)
        log_event(logger, logging.INFO, "playback.resumed")

    def replay(self) -> None:
        log_event(logger, logging.INFO, "playback.replay.requested")
        state = self._session.snapshot()
        text = state.text
        source = state.source or "replay"
        if text:
            self._begin_speech(text, source=source)
        else:
            log_event(logger, logging.DEBUG, "playback.replay.ignored_no_text")

    def read_current(self) -> None:
        """Run the same native capture used by the global hotkey."""
        log_event(logger, logging.INFO, "capture.button.requested")
        self._trigger_button_capture()

    def _trigger_button_capture(self) -> None:
        try:
            self._hotkeys.trigger()
        except Exception:
            log_exception(logger, "capture.button.failed")
            self._player.show()

    def toggle_clipboard_mode(self) -> None:
        with self._state_lock:
            self._clipboard_mode = not self._clipboard_mode
            enabled = self._clipboard_mode
        self._player.set_clipboard_mode(enabled)
        log_event(
            logger,
            logging.INFO,
            "capture.mode.changed",
            mode="clipboard" if enabled else "auto",
        )

    def toggle_auto_hide(self) -> None:
        with self._state_lock:
            self._auto_hide = not self._auto_hide
            enabled = self._auto_hide
        self._player.set_auto_hide(enabled)
        log_event(
            logger,
            logging.INFO,
            "player.auto_hide.changed",
            enabled=enabled,
        )

    def toggle_speech_debug(self) -> None:
        with self._state_lock:
            self._speech_debug_enabled = not self._speech_debug_enabled
            enabled = self._speech_debug_enabled
        self._player.set_debug_enabled(enabled)
        log_event(logger, logging.INFO, "speech.debug.changed", enabled=enabled)

    def toggle_speech_backend(self) -> None:
        with self._state_lock:
            if self._backend_switching:
                return
            self._backend_switching = True
            current = self._speech_backend
            target = "windows" if current == "supertonic" else "supertonic"
        self.stop()
        self._player.set_speech_backend(target, loading=True)
        threading.Thread(
            target=self._load_speech_backend,
            args=(current, target),
            daemon=True,
            name=f"VoiceBackend-{target}",
        ).start()

    def _load_speech_backend(self, current: str, target: str) -> None:
        try:
            speaker = self._speakers.get(target)
            if speaker is None:
                backend = (
                    "supertonic"
                    if target == "supertonic"
                    else self._windows_speech_backend
                )
                speaker = create_speaker(
                    replace(self._config, speech_backend=backend),
                    self._on_word,
                    self._on_speech_debug,
                )
                self._speakers[target] = speaker
            with self._state_lock:
                if self._shutting_down:
                    return
                self._speaker = speaker
                self._speech_backend = target
            self._player.call_soon(
                lambda: self._player.set_speech_backend(target)
            )
            log_event(
                logger,
                logging.INFO,
                "speaker.backend.changed",
                backend=target,
            )
        except Exception as error:
            log_exception(logger, "speaker.backend.change_failed", backend=target)
            self._player.call_soon(
                lambda: self._player.set_speech_backend(current)
            )
            self._player.call_soon(
                lambda message=str(error): self._player.show_backend_error(message)
            )
        finally:
            with self._state_lock:
                self._backend_switching = False

    def start_hotkey_capture(self) -> None:
        log_event(logger, logging.INFO, "hotkey.capture.requested")
        if self._session.snapshot().speaking:
            log_event(logger, logging.INFO, "hotkey.capture.ignored_while_speaking")
            return
        started = self._hotkeys.start_capture(
            timeout_seconds=self._config.capture_timeout_seconds,
            on_preview=lambda combo: self._player.call_soon(
                lambda: self._player.show_capture_preview(combo)
            ),
            on_complete=lambda combo: self._player.call_soon(
                lambda: self._apply_hotkey(combo)
            ),
            on_cancel=lambda: self._player.call_soon(self._cancel_hotkey_capture),
        )
        if started:
            self._player.show_capture_started()
            log_event(logger, logging.INFO, "hotkey.capture.started")
        else:
            log_event(logger, logging.DEBUG, "hotkey.capture.already_active")

    def shutdown(self) -> None:
        if self._shutting_down:
            log_event(logger, logging.DEBUG, "app.shutdown.duplicate_ignored")
            return
        log_event(logger, logging.INFO, "app.shutdown.started")
        self._shutting_down = True
        for speaker in self._speakers.values():
            speaker.stop()
        self._hotkeys.close()
        self._ocr_capture.stop()
        self._tray.stop()
        self._player.destroy()
        log_event(logger, logging.INFO, "app.shutdown.completed")

    def _on_hotkey(self, selected_text: str, activated_at: float) -> None:
        log_event(logger, logging.INFO, "hotkey.activated", hotkey=self._hotkeys.hotkey)
        if self._hotkeys.capturing:
            log_event(logger, logging.DEBUG, "hotkey.ignored_during_capture")
            return
        now = activated_at
        with self._state_lock:
            elapsed = now - self._last_hotkey_time
            if elapsed < self._config.hotkey_debounce_seconds:
                log_event(
                    logger,
                    logging.DEBUG,
                    "hotkey.debounced",
                    elapsed_seconds=round(elapsed, 4),
                )
                return
            self._last_hotkey_time = now
            clipboard_mode = self._clipboard_mode
            session = self._session.snapshot()
            speaking_now = session.speaking
            speaking_at_activation = was_speaking_at(
                activated_at,
                session.started_at,
                session.ended_at,
            )

        requested_mode = "clipboard" if clipboard_mode else "auto"
        log_event(
            logger,
            logging.INFO,
            "capture.started",
            mode=requested_mode,
            already_speaking=speaking_at_activation,
            speaking_when_capture_completed=speaking_now,
        )
        capture = resolve_capture(
            selected_text,
            self._clipboard.read_text,
            force_clipboard=clipboard_mode,
        )
        if capture.source == "clipboard_fallback":
            log_event(
                logger,
                logging.INFO,
                "capture.fallback_to_clipboard",
                reason="selection_empty",
                selected_length=len(selected_text),
                clipboard_length=len(capture.raw_text),
            )
        log_event(
            logger,
            logging.INFO,
            "capture.completed",
            source=capture.source,
            raw_length=len(capture.raw_text),
            cleaned_length=len(capture.text),
            raw_preview=text_preview(capture.raw_text),
            cleaned_preview=text_preview(capture.text),
        )
        if not capture.text:
            log_event(
                logger,
                logging.WARNING,
                "capture.empty",
                source=capture.source,
                action="stop" if speaking_at_activation else "show_player",
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
            log_event(
                logger,
                logging.INFO,
                "hotkey.repeated_active_text",
                action="stop",
                text_length=len(capture.text),
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
            clipboard_mode = self._clipboard_mode
            session = self._session.snapshot()
            stop_clipboard_speech = should_stop_clipboard_speech_immediately(
                speaking=session.speaking,
                source=session.source,
            )
        if backend_switching:
            log_event(logger, logging.INFO, "hotkey.ignored_backend_loading")
            self._player.call_soon(self._player.show_backend_loading)
            return True
        if stop_clipboard_speech:
            log_event(
                logger,
                logging.INFO,
                "hotkey.clipboard_speech.immediate_stop",
            )
            self.stop()
            with self._state_lock:
                self._last_hotkey_time = 0.0
            return True
        if clipboard_mode:
            log_event(
                logger,
                logging.DEBUG,
                "hotkey.clipboard_mode.direct_capture",
            )
            self._on_hotkey("", time.monotonic())
            return True
        return False

    def _begin_speech(self, text: str, *, source: str = "replay") -> None:
        with self._state_lock:
            if self._backend_switching:
                log_event(logger, logging.INFO, "speech.ignored_backend_loading")
                self._player.call_soon(self._player.show_backend_loading)
                return
        log_event(
            logger,
            logging.INFO,
            "speech.queue.requested",
            text_length=len(text),
            text_preview=text_preview(text),
        )
        speaker = self._speaker
        self._player.call_soon(self._player.reset_speech_debug)
        try:
            generation = speaker.speak(text)
        except RuntimeError:
            log_exception(logger, "speech.queue.failed")
            return
        if generation is None:
            log_event(
                logger,
                logging.WARNING,
                "speech.queue.rejected",
                text_length=len(text),
                minimum_length=self._config.minimum_text_length,
            )
            return
        self._session.start(speaker, generation, text, source, time.monotonic())
        self._update_player(speaking=True, text=text)
        log_event(
            logger,
            logging.INFO,
            "speech.queued",
            generation=generation,
            text_length=len(text),
        )
        threading.Thread(
            target=self._wait_for_speech,
            args=(speaker, generation, text),
            daemon=True,
            name=f"SpeechWait-{generation}",
        ).start()

    def _wait_for_speech(
        self, speaker: Speaker, generation: int, text: str
    ) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "speech.wait.started",
            generation=generation,
        )
        if not speaker.wait_until_done(generation):
            log_event(
                logger,
                logging.INFO,
                "speech.wait.superseded",
                generation=generation,
            )
            return
        if not self._session.complete(speaker, generation, time.monotonic()):
            log_event(
                logger,
                logging.DEBUG,
                "speech.completion.stale",
                generation=generation,
            )
            return
        self._update_player(speaking=False, text=text)
        log_event(
            logger,
            logging.INFO,
            "speech.completed",
            generation=generation,
        )

    def _update_player(
        self, *, speaking: bool, paused: bool = False, text: str = ""
    ) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "ui.playback_update.queued",
            speaking=speaking,
            paused=paused,
            text_length=len(text),
        )
        self._player.call_soon(
            lambda: self._player.set_playback(
                speaking=speaking, paused=paused, text=text
            )
        )

    def _on_word(self, _text: str, position: int, length: int) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "speech.word_boundary",
            position=position,
            length=length,
        )
        self._player.highlight_word(position, length)

    def _on_speech_debug(self, event: SpeechDebugEvent) -> None:
        self._player.call_soon(
            lambda event=event: self._player.update_speech_debug(event)
        )

    def _on_ocr_text(self, captured_text: str) -> None:
        text = prepare_for_speech(captured_text)
        log_event(
            logger,
            logging.INFO,
            "ocr_capture.text_prepared",
            raw_length=len(captured_text),
            cleaned_length=len(text),
            cleaned_preview=text_preview(text),
        )
        if text:
            self._begin_speech(text, source="ocr")

    def _apply_hotkey(self, hotkey: str) -> None:
        log_event(logger, logging.INFO, "hotkey.rebind.requested", hotkey=hotkey)
        try:
            self._hotkeys.rebind(hotkey)
        except Exception:
            log_exception(logger, "hotkey.rebind.failed", hotkey=hotkey)
            self._player.show_idle_hint()
            return
        self._player.show_capture_complete(hotkey)
        self._tray.update_hotkey(hotkey)
        log_event(logger, logging.INFO, "hotkey.rebind.completed", hotkey=hotkey)

    def _cancel_hotkey_capture(self) -> None:
        log_event(logger, logging.INFO, "hotkey.capture.cancelled")
        self._player.set_hotkey(self._hotkeys.hotkey)
        self._player.show_idle_hint()

    @staticmethod
    def _enable_dpi_awareness() -> None:
        try:
            windows_libraries = getattr(ctypes, "windll", None)
            if windows_libraries is not None:
                # Per-monitor v2 keeps Tk's measured layout and the native window
                # size in agreement when displays use different scale factors.
                enabled = windows_libraries.user32.SetProcessDpiAwarenessContext(
                    ctypes.c_void_p(-4)
                )
                if enabled:
                    log_event(
                        logger,
                        logging.DEBUG,
                        "dpi_awareness.enabled",
                        mode="per_monitor_v2",
                    )
                else:
                    windows_libraries.shcore.SetProcessDpiAwareness(1)
                    log_event(
                        logger,
                        logging.DEBUG,
                        "dpi_awareness.enabled",
                        mode="system",
                    )
            else:
                log_event(logger, logging.DEBUG, "dpi_awareness.unavailable")
        except Exception:
            log_exception(logger, "dpi_awareness.failed")


def main() -> None:
    SelectSpeakApp().run()
