"""Status text shared by the Tk and WinUI players.

Both renderers show the same words for the same state, so the wording lives
here rather than being written twice and drifting apart.
"""

from __future__ import annotations

_KEY_NAMES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Win",
    "cmd": "Win",
    "esc": "Esc",
    "space": "Space",
}


def shortcut_label(hotkey: str) -> str:
    """Format a hotkey the way Windows writes shortcuts: Ctrl+Shift+S."""
    parts = [part.strip() for part in hotkey.split("+") if part.strip()]
    return "+".join(
        _KEY_NAMES.get(part.casefold(), part.upper() if len(part) == 1 else part.title()) for part in parts
    )


def idle_hint(hotkey: str, ocr_hotkey: str, *, clipboard_mode: bool) -> str:
    """The resting prompt, naming whichever source the capture will use."""
    target = "your clipboard" if clipboard_mode else "your selection or clipboard"
    return (
        f"Press {shortcut_label(hotkey)} to read {target}, "
        f"or {shortcut_label(ocr_hotkey)} to capture text on screen."
    )


def backend_loading_message(activity: str = "loading") -> str:
    if activity == "installing":
        return (
            "Opening Setup to install Supertonic and its local voice model. "
            "SelectSpeak will restart when installation finishes."
        )
    return "Loading the voice engine. Reading will be available when it is ready."
