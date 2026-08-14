from __future__ import annotations

import ctypes
import logging
import os

logger = logging.getLogger(__name__)

_MONITOR_DEFAULTTONEAREST = 2
_GWL_STYLE = -16
_WS_CAPTION = 0x00C00000
_SHELL_WINDOW_CLASSES = {"Progman", "Shell_TrayWnd", "WorkerW"}


class _Rect(ctypes.Structure):
    _fields_ = (
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    )


class _MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("size", ctypes.c_ulong),
        ("monitor", _Rect),
        ("work", _Rect),
        ("flags", ctypes.c_ulong),
    )


def foreground_window_is_fullscreen() -> bool:
    """Return whether the foreground application covers its nearest monitor."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.IsIconic.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rect)]
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        window = user32.GetForegroundWindow()
        if not window or user32.IsIconic(window) or not user32.IsWindowVisible(window):
            return False
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(window, class_name, len(class_name))
        if class_name.value in _SHELL_WINDOW_CLASSES:
            return False

        window_rect = _Rect()
        if not user32.GetWindowRect(window, ctypes.byref(window_rect)):
            return False
        monitor = user32.MonitorFromWindow(window, _MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return False
        monitor_info = _MonitorInfo(size=ctypes.sizeof(_MonitorInfo))
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            return False
        if not rectangle_covers_monitor(window_rect, monitor_info.monitor):
            return False
        style = user32.GetWindowLongPtrW(window, _GWL_STYLE)
        return not style & _WS_CAPTION
    except Exception:
        logger.exception("foreground.fullscreen_detection_failed")
        return False


def rectangle_covers_monitor(window: _Rect, monitor: _Rect, tolerance: int = 2) -> bool:
    """Return whether a window rectangle covers the monitor rectangle."""
    return (
        window.left <= monitor.left + tolerance
        and window.top <= monitor.top + tolerance
        and window.right >= monitor.right - tolerance
        and window.bottom >= monitor.bottom - tolerance
    )
