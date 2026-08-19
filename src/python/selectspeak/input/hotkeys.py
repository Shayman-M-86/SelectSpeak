import logging
import threading
from collections.abc import Callable

from .native import NativeInputAdapter

logger = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(
        self,
        hotkey: str,
        handler: Callable[[str, float], None],
        activation_handler: Callable[[], bool],
        *,
        native_dll: str = "",
    ) -> None:
        self.hotkey = hotkey
        self._handler = handler
        self._activation_handler = activation_handler
        self._native_dll = native_dll
        self._listener: NativeInputAdapter | None = None
        self._timeout_timer: threading.Timer | None = None
        self._capture_active = False
        self._lock = threading.RLock()
        logger.debug("hotkey.manager.created hotkey=%s", hotkey)

    @property
    def capturing(self) -> bool:
        with self._lock:
            return self._capture_active

    def register(self) -> None:
        logger.info("hotkey.register.requested hotkey=%s", self.hotkey)
        with self._lock:
            if self._listener is not None:
                logger.debug("hotkey.register.already_registered")
                return
            listener = NativeInputAdapter(
                self.hotkey,
                self._handler,
                self._activation_handler,
                dll_path=self._native_dll,
            )
            listener.start()
            self._listener = listener
        logger.info(
            "hotkey.register.completed hotkey=%s engine=%s",
            self.hotkey,
            "native_windows",
        )

    def rebind(self, hotkey: str) -> None:
        logger.info(
            "hotkey.listener.rebind.started previous_hotkey=%s new_hotkey=%s",
            self.hotkey,
            hotkey,
        )
        with self._lock:
            listener = self._require_listener()
            listener.rebind(hotkey)
            self.hotkey = hotkey
        logger.info(
            "hotkey.listener.rebind.completed hotkey=%s engine=%s",
            hotkey,
            "native_windows",
        )

    def start_capture(
        self,
        *,
        timeout_seconds: float,
        on_preview: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> bool:
        """Record a shortcut, suppressing every keystroke until it finishes."""
        logger.info("hotkey.capture_listener.requested timeout_seconds=%s", timeout_seconds)
        with self._lock:
            if self._capture_active:
                return False
            self._capture_active = True
            self._on_preview = on_preview
            self._on_complete = on_complete
            self._on_cancel = on_cancel
            try:
                self._require_listener().start_recording(
                    self._recording_preview,
                    self._recording_complete,
                    self._recording_cancel,
                )
            except Exception:
                self._capture_active = False
                raise
            self._timeout_timer = threading.Timer(timeout_seconds, lambda: self.cancel_capture(on_cancel))
            self._timeout_timer.daemon = True
            self._timeout_timer.start()
        logger.info("hotkey.capture_listener.started engine=%s", "native_windows")
        return True

    def cancel_capture(self, callback: Callable[[], None] | None = None) -> None:
        with self._lock:
            if not self._capture_active:
                return
            self._finish_capture()
        (callback or self._on_cancel)()

    def close(self) -> None:
        logger.info("hotkey.manager.close.started")
        with self._lock:
            if self._capture_active:
                self._finish_capture()
            listener = self._listener
            self._listener = None
        if listener is not None:
            listener.stop()
        logger.info("hotkey.manager.close.completed")

    def trigger(self) -> None:
        with self._lock:
            listener = self._require_listener()
        listener.trigger()

    def _recording_preview(self, hotkey: str) -> None:
        with self._lock:
            if not self._capture_active:
                return
            callback = self._on_preview
        callback(hotkey)

    def _recording_complete(self, hotkey: str) -> None:
        with self._lock:
            if not self._capture_active:
                return
            callback = self._on_complete
            self._finish_capture()
        logger.info("hotkey.capture.completed combo=%s engine=%s", hotkey, "native_windows")
        callback(hotkey)

    def _recording_cancel(self) -> None:
        with self._lock:
            if not self._capture_active:
                return
            callback = self._on_cancel
            self._finish_capture()
        callback()

    def _finish_capture(self) -> None:
        self._capture_active = False
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None
        if self._listener is not None:
            self._listener.stop_recording()

    def _require_listener(self) -> NativeInputAdapter:
        if self._listener is None:
            raise RuntimeError("Global hotkey listener is not registered")
        return self._listener
