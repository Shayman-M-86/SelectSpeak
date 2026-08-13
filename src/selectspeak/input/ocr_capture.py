from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from typing import Any

from ..logging_setup import text_preview
from ..native import get_native_bridge
from .keymap import to_windows_hotkey

logger = logging.getLogger(__name__)

OCR_COMPLETED = 1
OCR_CANCELLED = 2
OCR_FAILED = 3

_OCR_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_wchar_p,
    ctypes.c_uint,
    ctypes.c_void_p,
)


class OcrCaptureError(RuntimeError):
    pass


class OcrCaptureHotkey:
    """Own the native frozen-screen selector and local Windows OCR bridge."""

    def __init__(
        self,
        hotkey: str,
        on_text: Callable[[str], None],
        *,
        dll_path: str = "",
        language: str = "",
    ) -> None:
        self.hotkey = hotkey
        self.language = language
        self._on_text = on_text
        self._bridge = get_native_bridge(dll_path)
        self._dll = self._bridge.library
        self._configure_api()
        self._callback = _OCR_CALLBACK(self._on_result)
        self._started = False

    @property
    def active(self) -> bool:
        return bool(self._dll.ss_ocr_is_active()) if self._started else False

    def start(self) -> None:
        if self._started:
            return
        modifiers, virtual_key = to_windows_hotkey(self.hotkey)
        if self._dll.ss_ocr_start(
            modifiers,
            virtual_key,
            self.language or None,
            self._callback,
            None,
        ):
            raise OcrCaptureError(self._last_error())
        self._started = True
        logger.info(
            "ocr_hotkey.registered hotkey=%s language=%s implementation=%s",
            self.hotkey,
            self.language or "automatic",
            "native_windows_ocr",
        )

    def cancel(self) -> None:
        if self._started:
            self._dll.ss_ocr_cancel()

    def stop(self) -> None:
        if self._started:
            self._dll.ss_ocr_stop()
            self._started = False
            logger.info("ocr_hotkey.unregistered")

    def _configure_api(self) -> None:
        self._dll.ss_ocr_start.argtypes = [
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_wchar_p,
            _OCR_CALLBACK,
            ctypes.c_void_p,
        ]
        self._dll.ss_ocr_start.restype = ctypes.c_int
        self._dll.ss_ocr_cancel.argtypes = []
        self._dll.ss_ocr_cancel.restype = None
        self._dll.ss_ocr_is_active.argtypes = []
        self._dll.ss_ocr_is_active.restype = ctypes.c_int
        self._dll.ss_ocr_stop.argtypes = []
        self._dll.ss_ocr_stop.restype = None
        self._dll.ss_ocr_last_error.argtypes = [ctypes.c_char_p, ctypes.c_uint]
        self._dll.ss_ocr_last_error.restype = ctypes.c_uint

    def _on_result(
        self,
        text: str | None,
        status: int,
        _context: Any,
    ) -> None:
        captured = text or ""
        if status == OCR_CANCELLED:
            logger.info("ocr_capture.cancelled")
            return
        if status == OCR_FAILED:
            logger.error("ocr_capture.failed error=%s", self._last_error())
            return
        if status != OCR_COMPLETED:
            logger.error(
                "ocr_capture.failed error=%s",
                f"Native OCR returned unknown status {status}",
            )
            return

        logger.log(
            logging.INFO if captured.strip() else logging.WARNING,
            "ocr_capture.completed text_length=%s text_preview=%s",
            len(captured),
            text_preview(captured),
        )
        if not captured.strip():
            return
        threading.Thread(
            target=self._run_handler,
            args=(captured,),
            daemon=True,
            name="NativeOcrResult",
        ).start()

    def _run_handler(self, text: str) -> None:
        try:
            self._on_text(text)
        except Exception:
            logger.exception("ocr_capture.handler.failed")

    def _last_error(self) -> str:
        required = self._dll.ss_ocr_last_error(None, 0)
        buffer = ctypes.create_string_buffer(max(required, 1))
        self._dll.ss_ocr_last_error(buffer, len(buffer))
        return buffer.value.decode("utf-8", errors="replace")
