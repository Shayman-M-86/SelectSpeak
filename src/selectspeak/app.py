import ctypes
import logging
import threading
import time

from .clipboard import ClipboardService
from .config import DEFAULT_CONFIG, AppConfig
from .hotkeys import HotkeyManager
from .logging_setup import log_event, log_exception, text_preview
from .speaker import SapiSpeaker
from .text import tidy_text
from .ui.player import PlayerWindow
from .ui.tray import TrayController

logger = logging.getLogger(__name__)


class SelectSpeakApp:
    """Coordinate application state while delegating platform-specific work."""

    def __init__(self, config: AppConfig = DEFAULT_CONFIG) -> None:
        self._config = config
        self._state_lock = threading.RLock()
        self._last_text = ""
        self._speech_generation: int | None = None
        self._is_speaking = False
        self._is_paused = False
        self._clipboard_mode = False
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
            on_play=self.replay,
            on_pause=self.pause,
            on_resume=self.resume,
            on_stop=self.stop,
            on_toggle_clipboard=self.toggle_clipboard_mode,
            on_capture_hotkey=self.start_hotkey_capture,
        )
        self._clipboard = ClipboardService(self._config)
        self._speaker = SapiSpeaker(self._config, self._on_word)
        self._hotkeys = HotkeyManager(self._config.default_hotkey, self._on_hotkey)
        self._tray = TrayController(
            app_name=self._config.app_name,
            hotkey=self._config.default_hotkey,
            on_show=lambda: self._player.call_soon(self._player.show),
            on_quit=lambda: self._player.call_soon(self.shutdown),
        )

        self._hotkeys.register()
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
        self._speaker.stop()
        with self._state_lock:
            self._speech_generation = None
            self._is_speaking = False
            self._is_paused = False
            text = self._last_text
        self._update_player(speaking=False, text=text)
        log_event(
            logger,
            logging.INFO,
            "playback.stopped",
            last_text_preview=text_preview(text),
        )

    def pause(self) -> None:
        log_event(logger, logging.DEBUG, "playback.pause.requested")
        with self._state_lock:
            if not self._is_speaking or self._is_paused:
                log_event(
                    logger,
                    logging.DEBUG,
                    "playback.pause.ignored",
                    speaking=self._is_speaking,
                    paused=self._is_paused,
                )
                return
            self._is_paused = True
            text = self._last_text
        self._speaker.pause()
        self._update_player(speaking=True, paused=True, text=text)
        log_event(logger, logging.INFO, "playback.paused")

    def resume(self) -> None:
        log_event(logger, logging.DEBUG, "playback.resume.requested")
        with self._state_lock:
            if not self._is_speaking or not self._is_paused:
                log_event(
                    logger,
                    logging.DEBUG,
                    "playback.resume.ignored",
                    speaking=self._is_speaking,
                    paused=self._is_paused,
                )
                return
            self._is_paused = False
            text = self._last_text
        self._speaker.resume()
        self._update_player(speaking=True, paused=False, text=text)
        log_event(logger, logging.INFO, "playback.resumed")

    def replay(self) -> None:
        log_event(logger, logging.INFO, "playback.replay.requested")
        with self._state_lock:
            text = self._last_text
        if text:
            self._begin_speech(text)
        else:
            log_event(logger, logging.DEBUG, "playback.replay.ignored_no_text")

    def toggle_clipboard_mode(self) -> None:
        with self._state_lock:
            self._clipboard_mode = not self._clipboard_mode
            enabled = self._clipboard_mode
        self._player.set_clipboard_mode(enabled)
        log_event(
            logger,
            logging.INFO,
            "capture.mode.changed",
            mode="clipboard" if enabled else "selection",
        )

    def start_hotkey_capture(self) -> None:
        log_event(logger, logging.INFO, "hotkey.capture.requested")
        with self._state_lock:
            if self._is_speaking:
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
        self._speaker.stop()
        self._hotkeys.close()
        self._tray.stop()
        self._player.destroy()
        log_event(logger, logging.INFO, "app.shutdown.completed")

    def _on_hotkey(self) -> None:
        log_event(logger, logging.INFO, "hotkey.activated", hotkey=self._hotkeys.hotkey)
        if self._hotkeys.capturing:
            log_event(logger, logging.DEBUG, "hotkey.ignored_during_capture")
            return
        now = time.monotonic()
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
            speaking = self._is_speaking

        source = "clipboard" if clipboard_mode else "selection"
        log_event(
            logger,
            logging.INFO,
            "capture.started",
            source=source,
            already_speaking=speaking,
        )
        raw_text = (
            self._clipboard.read_text()
            if clipboard_mode
            else self._clipboard.capture_selection()
        )
        text = tidy_text(raw_text or "")
        log_event(
            logger,
            logging.INFO,
            "capture.completed",
            source=source,
            raw_length=len(raw_text or ""),
            cleaned_length=len(text),
            raw_preview=text_preview(raw_text),
            cleaned_preview=text_preview(text),
        )
        if not text:
            log_event(
                logger,
                logging.WARNING,
                "capture.empty",
                source=source,
                action="stop" if speaking else "show_player",
            )
            if speaking:
                self.stop()
            else:
                self._player.call_soon(self._player.show)
            return
        self._begin_speech(text)

    def _begin_speech(self, text: str) -> None:
        log_event(
            logger,
            logging.INFO,
            "speech.queue.requested",
            text_length=len(text),
            text_preview=text_preview(text),
        )
        try:
            generation = self._speaker.speak(text)
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
        with self._state_lock:
            self._last_text = text
            self._speech_generation = generation
            self._is_speaking = True
            self._is_paused = False
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
            args=(generation, text),
            daemon=True,
            name=f"SpeechWait-{generation}",
        ).start()

    def _wait_for_speech(self, generation: int, text: str) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "speech.wait.started",
            generation=generation,
        )
        if not self._speaker.wait_until_done(generation):
            log_event(
                logger,
                logging.INFO,
                "speech.wait.superseded",
                generation=generation,
            )
            return
        with self._state_lock:
            if self._speech_generation != generation:
                log_event(
                    logger,
                    logging.DEBUG,
                    "speech.completion.stale",
                    generation=generation,
                    current_generation=self._speech_generation,
                )
                return
            self._speech_generation = None
            self._is_speaking = False
            self._is_paused = False
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
                windows_libraries.shcore.SetProcessDpiAwareness(1)
                log_event(logger, logging.DEBUG, "dpi_awareness.enabled")
            else:
                log_event(logger, logging.DEBUG, "dpi_awareness.unavailable")
        except Exception:
            log_exception(logger, "dpi_awareness.failed")


def main() -> None:
    SelectSpeakApp().run()
