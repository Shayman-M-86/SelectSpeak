"""Selected-text capture, clipboard, and global-hotkey services."""

from .capture import CaptureResult, resolve_capture
from .clipboard import ClipboardService
from .hotkeys import HotkeyManager
from .ocr_capture import OcrCaptureHotkey

__all__ = [
    "CaptureResult",
    "ClipboardService",
    "HotkeyManager",
    "OcrCaptureHotkey",
    "resolve_capture",
]
