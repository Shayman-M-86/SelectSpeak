import logging

from .logging_setup import log_event

logger = logging.getLogger(__name__)

_MODIFIER_ALIASES = {
    "left ctrl": "ctrl",
    "right ctrl": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "left shift": "shift",
    "right shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
    "left alt": "alt",
    "right alt": "alt",
    "alt_l": "alt",
    "alt_r": "alt",
    "alt_gr": "alt",
    "left windows": "windows",
    "right windows": "windows",
    "cmd": "windows",
    "cmd_l": "windows",
    "cmd_r": "windows",
}
_MODIFIER_NAMES = {"ctrl", "shift", "alt", "windows"}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "windows")
_AUTOHOTKEY_MODIFIERS = {
    "ctrl": "^",
    "alt": "!",
    "shift": "+",
    "windows": "#",
}
_AUTOHOTKEY_NAMED_KEYS = {
    "backspace": "Backspace",
    "tab": "Tab",
    "enter": "Enter",
    "esc": "Esc",
    "space": "Space",
    "page_up": "PgUp",
    "page_down": "PgDn",
    "end": "End",
    "home": "Home",
    "left": "Left",
    "up": "Up",
    "right": "Right",
    "down": "Down",
    "insert": "Insert",
    "delete": "Delete",
}
_AUTOHOTKEY_NAMED_KEYS.update({f"f{number}": f"F{number}" for number in range(1, 25)})


def normalize_key(name: str) -> str:
    lowered = name.lower()
    normalized = _MODIFIER_ALIASES.get(lowered, lowered)
    log_event(
        logger,
        logging.DEBUG,
        "key.normalized",
        input=name,
        output=normalized,
    )
    return normalized


def build_hotkey(keys: set[str]) -> str:
    """Build the stable, user-facing hotkey representation."""
    normalized = {normalize_key(key) for key in keys}
    modifiers = [key for key in _MODIFIER_ORDER if key in normalized]
    ordinary_keys = sorted(key for key in normalized if key not in _MODIFIER_NAMES)
    if not ordinary_keys:
        log_event(
            logger,
            logging.DEBUG,
            "hotkey.built",
            keys=sorted(keys),
            result="",
            reason="modifier_only",
        )
        return ""
    result = "+".join([*modifiers, *ordinary_keys])
    log_event(
        logger,
        logging.DEBUG,
        "hotkey.built",
        keys=sorted(keys),
        result=result,
    )
    return result


def to_autohotkey_hotkey(hotkey: str) -> tuple[str, str]:
    """Translate ``alt+s`` into a suppressing AutoHotkey v2 hook hotkey."""
    parts = [normalize_key(part.strip()) for part in hotkey.split("+")]
    ordinary_keys = [part for part in parts if part not in _MODIFIER_NAMES]
    if len(ordinary_keys) != 1:
        raise ValueError("A global hotkey must contain exactly one trigger key")

    trigger = ordinary_keys[0]
    if len(trigger) == 1 and trigger.isalnum():
        ahk_trigger = trigger
    else:
        try:
            ahk_trigger = _AUTOHOTKEY_NAMED_KEYS[trigger]
        except KeyError as error:
            raise ValueError(f"Unsupported AutoHotkey key: {trigger}") from error

    modifiers = "".join(
        _AUTOHOTKEY_MODIFIERS[part] for part in _MODIFIER_ORDER if part in parts
    )
    result = f"${modifiers}{ahk_trigger}"
    log_event(
        logger,
        logging.DEBUG,
        "hotkey.translated_for_autohotkey",
        input=hotkey,
        output=result,
        trigger=ahk_trigger,
    )
    return result, ahk_trigger
