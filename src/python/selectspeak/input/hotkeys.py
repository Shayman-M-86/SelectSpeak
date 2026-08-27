import logging
import threading
from collections.abc import Callable

from .native import NativeInputAdapter

logger = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(
        self,
        hotkey: str,
        handler: Callable[[str, float, str, bool], None],
        activation_handler: Callable[[], bool],
        *,
        native_dll: str = "",
    ) -> None:
        self.hotkey = hotkey
        self._handler = handler
        self._activation_handler = activation_handler
        self._native_dll = native_dll
        self._listener: NativeInputAdapter | None = None
        self._lock = threading.RLock()
        logger.debug("hotkey.manager.created hotkey=%s", hotkey)

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

    def close(self) -> None:
        logger.info("hotkey.manager.close.started")
        with self._lock:
            listener = self._listener
            self._listener = None
        if listener is not None:
            listener.stop()
        logger.info("hotkey.manager.close.completed")

    def trigger(self) -> None:
        with self._lock:
            listener = self._require_listener()
        listener.trigger()

    def _require_listener(self) -> NativeInputAdapter:
        if self._listener is None:
            raise RuntimeError("Global hotkey listener is not registered")
        return self._listener
