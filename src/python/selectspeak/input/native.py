from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from ..diagnostics import text_preview
from ..native import ActivationCallback, CaptureCallback, get_native_bridge
from .keymap import to_windows_hotkey

logger = logging.getLogger(__name__)


class NativeInputError(RuntimeError):
    pass


class NativeInputAdapter:
    """Own the native global-hotkey and selected-text capture bridge."""

    def __init__(
        self,
        hotkey: str,
        handler: Callable[[str, float, str, bool], None],
        activation_handler: Callable[[], bool],
        dll_path: str = "",
    ) -> None:
        self.hotkey = hotkey
        self._handler = handler
        self._activation_handler = activation_handler
        self._bridge = get_native_bridge(dll_path)
        self._dll = self._bridge.library
        self._callback = CaptureCallback(self._on_capture)
        self._activation_callback = ActivationCallback(self._on_activation)
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

    def _on_capture(self, text: str | None, _context: Any) -> None:
        captured = text or ""
        activated_ms = self._dll.ss_input_last_activation_time_ms()
        kernel = ctypes.windll.kernel32
        kernel.GetTickCount64.restype = ctypes.c_ulonglong
        capture_latency_ms = max(0, kernel.GetTickCount64() - activated_ms)
        activated_at = time.monotonic() - capture_latency_ms / 1000
        clipboard_fallback = self._last_clipboard_fallback()
        source_id = self._dll.ss_input_last_capture_source()
        source = {
            1: "ui_automation",
            2: "wm_copy",
            3: "synthetic_copy",
            4: "unresolved",
        }.get(source_id, "empty")
        if source == "unresolved":
            # A copy was sent but the target hadn't finished by the time we
            # stopped waiting. The pre-capture clipboard snapshot must not be
            # spoken as if it were the selection: a late copy could still land
            # after this point, so treat the outcome as unknown, not empty.
            clipboard_fallback = ""
        capture_trace = self._last_capture_trace()
        if capture_trace:
            logger.info("native_input.selection_capture %s", capture_trace)
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
            args=(captured, activated_at, clipboard_fallback, source == "unresolved"),
            daemon=True,
            name="NativeInputCapture",
        ).start()

    def _on_activation(self, _context: Any) -> int:
        try:
            return int(self._activation_handler())
        except Exception:
            logger.exception("native_input.activation_handler.failed")
            return 0

    def _run_handler(
        self, text: str, activated_at: float, clipboard_fallback: str, capture_unresolved: bool
    ) -> None:
        try:
            self._handler(text, activated_at, clipboard_fallback, capture_unresolved)
        except Exception:
            logger.exception("native_input.handler.failed")

    def _last_error(self) -> str:
        required = self._dll.ss_input_last_error(None, 0)
        buffer = ctypes.create_string_buffer(max(required, 1))
        self._dll.ss_input_last_error(buffer, len(buffer))
        return buffer.value.decode("utf-8", errors="replace")

    def _last_clipboard_fallback(self) -> str:
        """Read what the clipboard held before this capture touched it.

        The native layer copies this by value before it empties the clipboard
        to probe for a selection, so it stays correct even when restoring the
        clipboard afterwards fails.
        """
        required = self._dll.ss_input_last_clipboard_fallback(None, 0)
        buffer = ctypes.create_unicode_buffer(max(required, 1))
        self._dll.ss_input_last_clipboard_fallback(buffer, len(buffer))
        return buffer.value

    def _last_capture_trace(self) -> str:
        required = self._dll.ss_input_last_capture_trace(None, 0)
        buffer = ctypes.create_string_buffer(max(required, 1))
        self._dll.ss_input_last_capture_trace(buffer, len(buffer))
        return buffer.value.decode("utf-8", errors="replace")
