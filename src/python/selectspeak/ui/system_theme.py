"""Whether Windows is running its apps in dark mode.

The player is a WinUI window and follows the system theme itself, so the only
thing left that needs to ask is the tray icon: shell icons take the tray's own
contrast rather than an app colour, so the glyph is drawn in the opposite
polarity to the taskbar.
"""

from __future__ import annotations

import logging
import os

if os.name == "nt":
    import winreg
else:
    winreg = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def apps_use_dark_theme() -> bool:
    """Report the user's app theme, defaulting to dark when it is unreadable."""
    if winreg is None:
        return True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except OSError:
        logger.debug("theme.light_mode.unavailable")
        return True
    return not bool(value)
