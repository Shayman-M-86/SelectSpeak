import logging
import threading
from collections.abc import Callable
from functools import partial
from typing import Protocol, cast

from pynput import keyboard

from .autohotkey import AutoHotkeySidecar
from .keymap import build_hotkey, normalize_key
from .logging_setup import log_event

logger = logging.getLogger(__name__)


class KeyboardListener(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class HotkeyManager:
    def __init__(self, hotkey: str, handler: Callable[[str], None]) -> None:
        self.hotkey = hotkey
        self._handler = handler
        self._hotkey_listener: AutoHotkeySidecar | None = None
        self._capture_listener: KeyboardListener | None = None
        self._release_timer: threading.Timer | None = None
        self._timeout_timer: threading.Timer | None = None
        self._capture_active = False
        self._held: set[str] = set()
        self._last_combo: set[str] = set()
        self._lock = threading.RLock()
        log_event(logger, logging.DEBUG, "hotkey.manager.created", hotkey=hotkey)

    @property
    def capturing(self) -> bool:
        with self._lock:
            return self._capture_active

    def register(self) -> None:
        log_event(logger, logging.INFO, "hotkey.register.requested", hotkey=self.hotkey)
        with self._lock:
            if self._hotkey_listener is not None:
                log_event(logger, logging.DEBUG, "hotkey.register.already_registered")
                return
            self._hotkey_listener = self._create_hotkey_listener(self.hotkey)
            self._hotkey_listener.start()
        log_event(
            logger,
            logging.INFO,
            "hotkey.register.completed",
            hotkey=self.hotkey,
            engine="autohotkey_v2",
        )

    def rebind(self, hotkey: str) -> None:
        """Register the new listener before retiring the old one."""
        log_event(
            logger,
            logging.INFO,
            "hotkey.listener.rebind.started",
            previous_hotkey=self.hotkey,
            new_hotkey=hotkey,
        )
        new_listener = self._create_hotkey_listener(hotkey)
        new_listener.start()
        with self._lock:
            old_listener = self._hotkey_listener
            self.hotkey = hotkey
            self._hotkey_listener = new_listener
        if old_listener is not None:
            old_listener.stop()
        log_event(
            logger,
            logging.INFO,
            "hotkey.listener.rebind.completed",
            hotkey=hotkey,
        )

    def start_capture(
        self,
        *,
        timeout_seconds: float,
        on_preview: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> bool:
        log_event(
            logger,
            logging.INFO,
            "hotkey.capture_listener.requested",
            timeout_seconds=timeout_seconds,
        )
        with self._lock:
            if self._capture_active:
                log_event(
                    logger,
                    logging.DEBUG,
                    "hotkey.capture_listener.already_active",
                )
                return False
            self._capture_active = True
            self._held.clear()
            self._last_combo.clear()
            self._on_preview = on_preview
            self._on_complete = on_complete
            self._on_cancel = on_cancel
            listener = cast(
                KeyboardListener,
                keyboard.Listener(
                    on_press=self._on_capture_press,
                    on_release=self._on_capture_release,
                    suppress=True,
                ),
            )
            self._capture_listener = listener
            listener.start()
            self._timeout_timer = threading.Timer(
                timeout_seconds, lambda: self.cancel_capture(on_cancel)
            )
            self._timeout_timer.daemon = True
            self._timeout_timer.start()
            log_event(logger, logging.INFO, "hotkey.capture_listener.started")
            return True

    def cancel_capture(self, callback: Callable[[], None] | None = None) -> None:
        log_event(logger, logging.INFO, "hotkey.capture_listener.cancel_requested")
        with self._lock:
            if not self._capture_active:
                log_event(
                    logger,
                    logging.DEBUG,
                    "hotkey.capture_listener.cancel_ignored",
                )
                return
            self._finish_capture()
        (callback or self._on_cancel)()

    def close(self) -> None:
        log_event(logger, logging.INFO, "hotkey.manager.close.started")
        with self._lock:
            if self._capture_active:
                self._finish_capture()
            listener = self._hotkey_listener
            self._hotkey_listener = None
        if listener is not None:
            listener.stop()
        log_event(logger, logging.INFO, "hotkey.manager.close.completed")

    def trigger(self) -> None:
        with self._lock:
            listener = self._hotkey_listener
        if listener is None:
            raise RuntimeError("Global hotkey listener is not registered")
        listener.trigger()

    def _create_hotkey_listener(self, hotkey: str) -> AutoHotkeySidecar:
        log_event(
            logger,
            logging.DEBUG,
            "hotkey.listener.creating",
            hotkey=hotkey,
            engine="autohotkey_v2",
        )
        return AutoHotkeySidecar(hotkey, self._handler)

    def _on_capture_press(self, key: object) -> None:
        name = self._key_name(key)
        log_event(
            logger,
            logging.DEBUG,
            "hotkey.capture.key_pressed",
            raw_key=str(key),
            normalized_key=name,
        )
        if not name:
            return
        with self._lock:
            if not self._capture_active:
                return
            if name == "esc":
                callback: Callable[[], None] | None = self._on_cancel
                self._finish_capture()
                log_event(logger, logging.INFO, "hotkey.capture.escape_pressed")
            else:
                self._held.add(name)
                self._last_combo = set(self._held)
                self._cancel_release_timer()
                combo = build_hotkey(self._held)
                callback = partial(self._on_preview, combo) if combo else None
                log_event(
                    logger,
                    logging.DEBUG,
                    "hotkey.capture.combo_updated",
                    held=sorted(self._held),
                    combo=combo,
                )
        if callback:
            callback()

    def _on_capture_release(self, key: object) -> None:
        name = self._key_name(key)
        log_event(
            logger,
            logging.DEBUG,
            "hotkey.capture.key_released",
            raw_key=str(key),
            normalized_key=name,
        )
        if not name:
            return
        with self._lock:
            if not self._capture_active:
                return
            self._held.discard(name)
            if not self._held and self._last_combo:
                self._cancel_release_timer()
                self._release_timer = threading.Timer(0.15, self._complete_capture)
                self._release_timer.daemon = True
                self._release_timer.start()
                log_event(
                    logger,
                    logging.DEBUG,
                    "hotkey.capture.finalize_scheduled",
                )

    def _complete_capture(self) -> None:
        log_event(logger, logging.DEBUG, "hotkey.capture.finalizing")
        with self._lock:
            if not self._capture_active:
                log_event(
                    logger,
                    logging.DEBUG,
                    "hotkey.capture.finalize_ignored",
                )
                return
            combo = build_hotkey(self._last_combo)
            if not combo:
                callback: Callable[[], None] = self._on_cancel
            else:
                callback = partial(self._on_complete, combo)
            self._finish_capture()
        log_event(
            logger,
            logging.INFO,
            "hotkey.capture.completed",
            combo=combo,
        )
        callback()

    def _finish_capture(self) -> None:
        log_event(logger, logging.DEBUG, "hotkey.capture.cleanup_started")
        self._capture_active = False
        self._cancel_release_timer()
        if self._timeout_timer:
            self._timeout_timer.cancel()
            self._timeout_timer = None
        if self._capture_listener is not None:
            self._capture_listener.stop()
            self._capture_listener = None
        log_event(logger, logging.DEBUG, "hotkey.capture.cleanup_completed")

    def _cancel_release_timer(self) -> None:
        if self._release_timer:
            self._release_timer.cancel()
            self._release_timer = None
            log_event(logger, logging.DEBUG, "hotkey.capture.release_timer_cancelled")

    @staticmethod
    def _key_name(key: object) -> str | None:
        if isinstance(key, keyboard.KeyCode):
            return key.char.lower() if key.char else None
        if isinstance(key, keyboard.Key):
            return normalize_key(key.name)
        return None
