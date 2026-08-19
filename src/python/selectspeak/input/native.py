from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from ..infrastructure.logging import text_preview
from ..native import get_native_bridge
from .keymap import from_windows_hotkey, to_windows_hotkey

logger = logging.getLogger(__name__)


class NativeInputError(RuntimeError):
    pass


_CAPTURE_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_wchar_p, ctypes.c_void_p)
_ACTIVATION_CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
_RECORD_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_void_p,
)


class NativeInputAdapter:
    """Own the native global-hotkey and selected-text capture bridge."""

    def __init__(
        self,
        hotkey: str,
        handler: Callable[[str, float], None],
        activation_handler: Callable[[], bool],
        dll_path: str = "",
    ) -> None:
        self.hotkey = hotkey
        self._handler = handler
        self._activation_handler = activation_handler
        self._bridge = get_native_bridge(dll_path)
        self._dll = self._bridge.library
        self._configure_api()
        self._callback = _CAPTURE_CALLBACK(self._on_capture)
        self._activation_callback = _ACTIVATION_CALLBACK(self._on_activation)
        self._record_callback: Any = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        modifiers, virtual_key = to_windows_hotkey(self.hotkey)
        if self._dll.ss_input_start(
            modifiers,
            virtual_key,
            self._callback,
            self._activation_callback,
            None,
        ):
            raise NativeInputError(self._last_error())
        self._started = True
        logger.info("native_input.started hotkey=%s", self.hotkey)

    def rebind(self, hotkey: str) -> None:
        modifiers, virtual_key = to_windows_hotkey(hotkey)
        if self._dll.ss_input_rebind(modifiers, virtual_key):
            raise NativeInputError(self._last_error())
        self.hotkey = hotkey
        logger.info("native_input.rebound hotkey=%s", hotkey)

    def trigger(self) -> None:
        if self._dll.ss_input_capture_now():
            raise NativeInputError(self._last_error())
        logger.info("native_input.capture.requested source=%s", "application_button")

    def stop(self) -> None:
        if self._started:
            self._dll.ss_input_stop()
            self._started = False
        logger.info("native_input.stopped hotkey=%s", self.hotkey)

    def start_recording(
        self,
        on_preview: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        def handle_recording(event: int, modifiers: int, virtual_key: int, _context: Any) -> None:
            hotkey = from_windows_hotkey(modifiers, virtual_key)
            logger.info(
                "native_input.recording.event event=%s modifiers=%s virtual_key=%s hotkey=%s",
                event,
                modifiers,
                virtual_key,
                hotkey,
            )
            if event == 1 and hotkey:
                on_preview(hotkey)
            elif event == 2 and hotkey:
                on_complete(hotkey)
            elif event == 3 or (event == 2 and not hotkey):
                on_cancel()

        callback = _RECORD_CALLBACK(handle_recording)
        if self._dll.ss_input_record_start(callback, None):
            raise NativeInputError(self._last_error())
        self._record_callback = callback
        logger.info("native_input.recording.started")

    def stop_recording(self) -> None:
        self._dll.ss_input_record_stop()
        logger.info("native_input.recording.stopped")

    def _configure_api(self) -> None:
        self._dll.ss_input_start.argtypes = [
            ctypes.c_uint,
            ctypes.c_uint,
            _CAPTURE_CALLBACK,
            _ACTIVATION_CALLBACK,
            ctypes.c_void_p,
        ]
        self._dll.ss_input_start.restype = ctypes.c_int
        self._dll.ss_input_rebind.argtypes = [ctypes.c_uint, ctypes.c_uint]
        self._dll.ss_input_rebind.restype = ctypes.c_int
        self._dll.ss_input_capture_now.argtypes = []
        self._dll.ss_input_capture_now.restype = ctypes.c_int
        self._dll.ss_input_record_start.argtypes = [
            _RECORD_CALLBACK,
            ctypes.c_void_p,
        ]
        self._dll.ss_input_record_start.restype = ctypes.c_int
        self._dll.ss_input_record_stop.argtypes = []
        self._dll.ss_input_record_stop.restype = None
        self._dll.ss_input_stop.argtypes = []
        self._dll.ss_input_stop.restype = None
        self._dll.ss_input_last_capture_source.argtypes = []
        self._dll.ss_input_last_capture_source.restype = ctypes.c_uint
        self._dll.ss_input_last_activation_time_ms.argtypes = []
        self._dll.ss_input_last_activation_time_ms.restype = ctypes.c_ulonglong
        self._dll.ss_input_last_error.argtypes = [ctypes.c_char_p, ctypes.c_uint]
        self._dll.ss_input_last_error.restype = ctypes.c_uint

    def _on_capture(self, text: str | None, _context: Any) -> None:
        captured = text or ""
        activated_ms = self._dll.ss_input_last_activation_time_ms()
        kernel = ctypes.windll.kernel32
        kernel.GetTickCount64.restype = ctypes.c_ulonglong
        capture_latency_ms = max(0, kernel.GetTickCount64() - activated_ms)
        activated_at = time.monotonic() - capture_latency_ms / 1000
        source_id = self._dll.ss_input_last_capture_source()
        source = {1: "ui_automation", 2: "clipboard"}.get(source_id, "empty")
        logger.log(
            logging.INFO if captured else logging.WARNING,
            "native_input.capture.completed captured=%s source=%s "
            "capture_latency_ms=%s text_length=%s text_preview=%s",
            bool(captured),
            source,
            capture_latency_ms,
            len(captured),
            text_preview(captured),
        )
        threading.Thread(
            target=self._run_handler,
            args=(captured, activated_at),
            daemon=True,
            name="NativeInputCapture",
        ).start()

    def _on_activation(self, _context: Any) -> int:
        try:
            return int(self._activation_handler())
        except Exception:
            logger.exception("native_input.activation_handler.failed")
            return 0

    def _run_handler(self, text: str, activated_at: float) -> None:
        try:
            self._handler(text, activated_at)
        except Exception:
            logger.exception("native_input.handler.failed")

    def _last_error(self) -> str:
        required = self._dll.ss_input_last_error(None, 0)
        buffer = ctypes.create_string_buffer(max(required, 1))
        self._dll.ss_input_last_error(buffer, len(buffer))
        return buffer.value.decode("utf-8", errors="replace")
