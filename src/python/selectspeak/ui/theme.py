"""Windows 11 Fluent palette, type ramp and icon glyphs for the player chrome.

Colours follow the user's personalisation settings so the overlay matches the
rest of the shell: light/dark comes from ``AppsUseLightTheme`` and the highlight
colour from the DWM ``AccentColor``. Every value falls back to the stock
Windows 11 dark neutrals when the registry is unreadable or we are off Windows.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter

logger = logging.getLogger(__name__)

_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_DWM_KEY = r"Software\Microsoft\Windows\DWM"

# Windows 11 keeps UI text at 9pt (Body) and never smaller than 8pt (Caption);
# the icon font is sized to match the text it sits beside.
FONT_FAMILY = "Segoe UI Variable Text"
FONT_FAMILY_DISPLAY = "Segoe UI Variable Display"
FONT_FAMILY_FALLBACK = "Segoe UI"
ICON_FAMILY = "Segoe Fluent Icons"
ICON_FAMILY_FALLBACK = "Segoe MDL2 Assets"
MONO_FAMILY = "Cascadia Mono"
MONO_FAMILY_FALLBACK = "Consolas"

BODY_SIZE = 9
CAPTION_SIZE = 8
SUBTITLE_SIZE = 10
ICON_SIZE = 10
CAPTION_ICON_SIZE = 8

# Air between paragraphs in the reader, applied to blank separator lines only
# so that every line holding words keeps an identical box height.
PARAGRAPH_GAP = 6

WINDOW_WIDTH = 680
MIN_IDLE_HEIGHT = 104
MIN_READING_HEIGHT = 268
MIN_DEBUG_READING_HEIGHT = 324
STATUS_WRAP_LENGTH = WINDOW_WIDTH - 32

# Segoe Fluent Icons private-use glyphs, named as in the Microsoft icon list.
ICON_APP = ""  # Volume
ICON_PLAY = ""  # Play
ICON_PAUSE = ""  # Pause
ICON_STOP = ""  # StopSolid, matching Windows media transport controls
ICON_REPLAY = ""  # Refresh
ICON_CLOSE = ""  # ChromeClose
ICON_MINIMIZE = ""  # ChromeMinimize
ICON_CHEVRON_DOWN = ""  # ChevronDown
ICON_KEYBOARD = ""  # KeyboardClassic
ICON_ACCEPT = ""  # Completed
ICON_WARNING = ""  # Warning
ICON_INFO = ""  # Info

# Fluent signals "working" with a moving indicator rather than a spun glyph, so
# playback activity is drawn as a real indeterminate progress bar.
PROGRESS_WIDTH = 44
PROGRESS_THICKNESS = 3
PROGRESS_INTERVAL_MS = 30


@dataclass(frozen=True, slots=True)
class Palette:
    """Fluent colour roles, mapped to Windows 11 light/dark system values."""

    dark: bool
    # Layering: solid background, then card/subtle fills on top of it.
    background: str
    card_background: str
    control_background: str
    control_background_hover: str
    control_background_pressed: str
    subtle_background: str
    # Strokes.
    border: str
    control_border: str
    divider: str
    # Text roles.
    text_primary: str
    text_secondary: str
    text_disabled: str
    text_on_accent: str
    # Signals.
    accent: str
    accent_hover: str
    accent_pressed: str
    success: str
    danger: str
    danger_hover: str
    # Reader word highlight.
    highlight_background: str
    highlight_foreground: str
    chunk_colours: tuple[str, ...]


_DARK = Palette(
    dark=True,
    background="#202020",
    card_background="#2b2b2b",
    control_background="#2d2d2d",
    control_background_hover="#333333",
    control_background_pressed="#272727",
    subtle_background="#2f2f2f",
    border="#1c1c1c",
    control_border="#383838",
    divider="#2f2f2f",
    text_primary="#ffffff",
    text_secondary="#c5c5c5",
    text_disabled="#7a7a7a",
    text_on_accent="#000000",
    accent="#4cc2ff",
    accent_hover="#63caff",
    accent_pressed="#42a1d8",
    success="#6ccb5f",
    danger="#ff99a4",
    danger_hover="#ffb3bb",
    highlight_background="#4cc2ff",
    highlight_foreground="#000000",
    chunk_colours=("#60cdff", "#6ccb5f", "#fce100", "#c39ea0"),
)

_LIGHT = Palette(
    dark=False,
    background="#f3f3f3",
    card_background="#fbfbfb",
    control_background="#fdfdfd",
    control_background_hover="#f6f6f6",
    control_background_pressed="#f5f5f5",
    subtle_background="#ededed",
    border="#d9d9d9",
    control_border="#e0e0e0",
    divider="#e5e5e5",
    text_primary="#1a1a1a",
    text_secondary="#5f5f5f",
    text_disabled="#9d9d9d",
    text_on_accent="#ffffff",
    accent="#005fb8",
    accent_hover="#1a6fc4",
    accent_pressed="#2d7bc6",
    success="#0f7b0f",
    danger="#c42b1c",
    danger_hover="#d13438",
    highlight_background="#005fb8",
    highlight_foreground="#ffffff",
    chunk_colours=("#005fb8", "#0f7b0f", "#9d5d00", "#8764b8"),
)


def _apps_use_light_theme() -> bool:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY) as key:
        value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
    return bool(value)


def _accent_colours() -> tuple[str, str, str]:
    """Return (accent, hover, pressed) from the DWM ABGR accent colour."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _DWM_KEY) as key:
        value, _kind = winreg.QueryValueEx(key, "AccentColor")
    # DWM stores the accent as 0xAABBGGRR.
    blue = (value >> 16) & 0xFF
    green = (value >> 8) & 0xFF
    red = value & 0xFF
    return (
        f"#{red:02x}{green:02x}{blue:02x}",
        _shift(red, green, blue, 0.12),
        _shift(red, green, blue, -0.12),
    )


def _shift(red: int, green: int, blue: int, amount: float) -> str:
    """Lighten (amount > 0) or darken a colour, as Fluent hover states do."""

    def channel(value: int) -> int:
        target = 255 if amount > 0 else 0
        return round(value + (target - value) * abs(amount))

    return f"#{channel(red):02x}{channel(green):02x}{channel(blue):02x}"


def _relative_luminance(colour: str) -> float:
    red, green, blue = (int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5))

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def load_palette() -> Palette:
    """Build the palette from Windows personalisation, falling back to dark."""
    if os.name != "nt":
        logger.debug("theme.palette.default reason=not_windows")
        return _DARK

    try:
        light = _apps_use_light_theme()
    except OSError:
        logger.debug("theme.light_mode.unavailable")
        light = False
    palette = _LIGHT if light else _DARK

    try:
        accent = _accent_colours()
    except OSError:
        logger.debug("theme.accent.unavailable")
        accent = None

    if accent is not None:
        palette = _with_accent(palette, accent)

    logger.info(
        "theme.palette.loaded mode=%s accent=%s",
        "dark" if palette.dark else "light",
        palette.accent,
    )
    return palette


def _with_accent(palette: Palette, accent: tuple[str, str, str]) -> Palette:
    """Apply the user's accent colour, keeping text on it readable.

    A saturated accent can fail contrast against the surface it labels, so the
    accent is only adopted for text when it stays legible; the fill roles always
    take it because they pair with an explicitly chosen foreground.
    """
    base, hover, pressed = accent
    text_accent = base if _contrast_ratio(base, palette.background) >= 4.5 else palette.accent
    on_accent = (
        "#000000" if _contrast_ratio("#000000", base) >= _contrast_ratio("#ffffff", base) else "#ffffff"
    )
    return replace(
        palette,
        accent=text_accent,
        accent_hover=hover,
        accent_pressed=pressed,
        text_on_accent=on_accent,
        highlight_background=base,
        highlight_foreground=on_accent,
    )


def resolve_font_family(root: tkinter.Misc, preferred: str, fallback: str) -> str:
    """Return ``preferred`` when Tk can see the family, else ``fallback``."""
    try:
        import tkinter.font as tkfont

        if preferred in tkfont.families(root):
            return preferred
    except Exception:
        logger.debug("theme.font.probe_failed family=%s", preferred)
    return fallback
