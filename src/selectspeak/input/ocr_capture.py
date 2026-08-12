from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from ..logging_setup import log_event, log_exception, text_preview
from .keymap import to_windows_hotkey

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
KEYEVENTF_KEYUP = 0x0002
OCR_HOTKEY_ID = 0x5344
VK_MENU = 0x12


class OcrCaptureError(RuntimeError):
    pass


class OcrCaptureHotkey:
    """Launch an OCR selector and read its next clipboard update aloud."""

    def __init__(
        self,
        hotkey: str,
        trigger_hotkey: str,
        clipboard_reader: Callable[[], str | None],
        on_text: Callable[[str], None],
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> None:
        self.hotkey = hotkey
        self.trigger_hotkey = trigger_hotkey
        self._clipboard_reader = clipboard_reader
        self._on_text = on_text
        self._timeout_seconds = timeout_seconds
        self._poll_seconds = poll_seconds
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._generation_lock = threading.Lock()
        self._capture_generation = 0
        self._thread_id = 0
        self._startup_error: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="OcrCaptureHotkey",
        )
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise OcrCaptureError("OCR hotkey listener did not start")
        if self._startup_error:
            raise OcrCaptureError(self._startup_error)

    def stop(self) -> None:
        self._stop.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, WM_QUIT, 0, 0
            )
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        modifiers, virtual_key = to_windows_hotkey(self.hotkey)
        if not user32.RegisterHotKey(
            None,
            OCR_HOTKEY_ID,
            modifiers | MOD_NOREPEAT,
            virtual_key,
        ):
            self._startup_error = (
                f"Could not register OCR hotkey {self.hotkey.upper()} "
                f"(Windows error {ctypes.get_last_error()})"
            )
            self._ready.set()
            return
        log_event(
            logger,
            logging.INFO,
            "ocr_hotkey.registered",
            hotkey=self.hotkey,
            trigger_hotkey=self.trigger_hotkey,
        )
        self._ready.set()
        message = wintypes.MSG()
        try:
            while not self._stop.is_set() and user32.GetMessageW(
                ctypes.byref(message), None, 0, 0
            ) > 0:
                if message.message == WM_HOTKEY and message.wParam == OCR_HOTKEY_ID:
                    with self._generation_lock:
                        self._capture_generation += 1
                        generation = self._capture_generation
                    threading.Thread(
                        target=self._capture,
                        args=(generation,),
                        daemon=True,
                        name="OcrClipboardCapture",
                    ).start()
        finally:
            user32.UnregisterHotKey(None, OCR_HOTKEY_ID)
            log_event(logger, logging.INFO, "ocr_hotkey.unregistered")

    def _capture(self, generation: int) -> None:
        try:
            user32 = ctypes.windll.user32
            sequence = int(user32.GetClipboardSequenceNumber())
            self._wait_for_hotkey_release()
            self._send_hotkey(self.trigger_hotkey)
            log_event(
                logger,
                logging.INFO,
                "ocr_capture.started",
                clipboard_sequence=sequence,
                trigger_hotkey=self.trigger_hotkey,
            )
            text = wait_for_clipboard_update(
                sequence,
                lambda: int(user32.GetClipboardSequenceNumber()),
                self._clipboard_reader,
                timeout_seconds=self._timeout_seconds,
                poll_seconds=self._poll_seconds,
                cancelled=lambda: (
                    self._stop.is_set() or not self._is_current(generation)
                ),
            )
            if text:
                log_event(
                    logger,
                    logging.INFO,
                    "ocr_capture.completed",
                    text_length=len(text),
                    text_preview=text_preview(text),
                )
                self._on_text(text)
            elif not self._stop.is_set():
                log_event(logger, logging.WARNING, "ocr_capture.timed_out")
        except Exception:
            log_exception(logger, "ocr_capture.failed")

    def _is_current(self, generation: int) -> bool:
        with self._generation_lock:
            return generation == self._capture_generation

    def _wait_for_hotkey_release(self) -> None:
        user32 = ctypes.windll.user32
        _modifiers, virtual_key = to_windows_hotkey(self.hotkey)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if not (
                user32.GetAsyncKeyState(VK_MENU) & 0x8000
                or user32.GetAsyncKeyState(virtual_key) & 0x8000
            ):
                return
            time.sleep(0.01)

    @staticmethod
    def _send_hotkey(hotkey: str) -> None:
        modifiers, virtual_key = to_windows_hotkey(hotkey)
        keys: list[int] = []
        if modifiers & 0x0008:
            keys.append(0x5B)  # Left Windows key
        if modifiers & 0x0002:
            keys.append(0x11)  # Control
        if modifiers & 0x0001:
            keys.append(VK_MENU)
        if modifiers & 0x0004:
            keys.append(0x10)  # Shift
        keys.append(virtual_key)
        for key in keys:
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        for key in reversed(keys):
            ctypes.windll.user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)


def wait_for_clipboard_update(
    initial_sequence: int,
    sequence_reader: Callable[[], int],
    text_reader: Callable[[], str | None],
    *,
    timeout_seconds: float,
    poll_seconds: float,
    cancelled: Callable[[], bool] = lambda: False,
) -> str | None:
    """Return text from the first usable clipboard update after activation."""
    deadline = time.monotonic() + timeout_seconds
    observed_sequence = initial_sequence
    while time.monotonic() < deadline and not cancelled():
        sequence = sequence_reader()
        if sequence != observed_sequence:
            observed_sequence = sequence
            text = text_reader()
            if text and text.strip():
                return text
        time.sleep(poll_seconds)
    return None
