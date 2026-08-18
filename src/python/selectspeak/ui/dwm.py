"""Desktop Window Manager attributes that give a Tk window native chrome.

A frameless Tk window has no shadow and square corners, which is the strongest
visual tell that it is not a Windows app. DWM will still round and shade the
window if we ask it to, so the player opts in here. Every call is best-effort:
the attributes are version-gated and simply ignored on older builds.
"""

from __future__ import annotations

import ctypes
import logging
import os

logger = logging.getLogger(__name__)

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34

_DWMWCP_ROUND = 2


def _set_attribute(handle: int, attribute: int, value: int) -> bool:
    dwmapi = ctypes.windll.dwmapi
    data = ctypes.c_int(value)
    result = dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(handle),
        ctypes.c_uint(attribute),
        ctypes.byref(data),
        ctypes.sizeof(data),
    )
    return result == 0


def _bgr(colour: str) -> int:
    """Convert ``#rrggbb`` to the 0x00BBGGRR integer DWM expects."""
    red = int(colour[1:3], 16)
    green = int(colour[3:5], 16)
    blue = int(colour[5:7], 16)
    return (blue << 16) | (green << 8) | red


def apply_native_frame(handle: int, *, dark: bool, border_colour: str | None = None) -> None:
    """Round the corners and match the shell's light/dark chrome.

    ``handle`` must be the top-level window, not the Tk client area, or DWM
    silently applies the attributes to the wrong window.
    """
    if os.name != "nt":
        return
    try:
        rounded = _set_attribute(handle, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
        _set_attribute(handle, _DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark))
        if border_colour is not None:
            _set_attribute(handle, _DWMWA_BORDER_COLOR, _bgr(border_colour))
        logger.info(
            "dwm.native_frame.applied window_handle=%s dark=%s rounded=%s",
            handle,
            dark,
            rounded,
        )
    except Exception:
        logger.exception("dwm.native_frame.failed window_handle=%s", handle)


def enable_shadow(handle: int) -> None:
    """Give a frameless window the standard DWM drop shadow.

    DWM only shades a window that reports a non-zero frame, so a 1px top margin
    is extended into the client area; the window stays visually frameless.
    """
    if os.name != "nt":
        return

    class _Margins(ctypes.Structure):
        _fields_ = (
            ("left", ctypes.c_int),
            ("right", ctypes.c_int),
            ("top", ctypes.c_int),
            ("bottom", ctypes.c_int),
        )

    try:
        margins = _Margins(0, 0, 1, 0)
        result = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
            ctypes.c_void_p(handle),
            ctypes.byref(margins),
        )
        logger.debug("dwm.shadow.applied window_handle=%s result=%s", handle, result)
    except Exception:
        logger.exception("dwm.shadow.failed window_handle=%s", handle)


def top_level_handle(client_handle: int) -> int:
    """Return the frame window that owns a Tk client area."""
    if os.name != "nt":
        return client_handle
    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetParent.restype = ctypes.c_void_p
    return user32.GetParent(ctypes.c_void_p(client_handle)) or client_handle
