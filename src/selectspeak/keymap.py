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
_WINDOWS_MODIFIERS = {
    "alt": 0x0001,
    "ctrl": 0x0002,
    "shift": 0x0004,
    "windows": 0x0008,
}
_WINDOWS_NAMED_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "esc": 0x1B,
    "space": 0x20,
    "page_up": 0x21,
    "page_down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
}
_WINDOWS_NAMED_KEYS.update({f"f{number}": 0x6F + number for number in range(1, 25)})
_WINDOWS_KEY_NAMES = {value: key for key, value in _WINDOWS_NAMED_KEYS.items()}


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


def to_windows_hotkey(hotkey: str) -> tuple[int, int]:
    """Translate a user-facing shortcut into RegisterHotKey values."""
    parts = [normalize_key(part.strip()) for part in hotkey.split("+")]
    ordinary_keys = [part for part in parts if part not in _MODIFIER_NAMES]
    if len(ordinary_keys) != 1:
        raise ValueError("A global hotkey must contain exactly one trigger key")

    trigger = ordinary_keys[0]
    if len(trigger) == 1 and trigger.isalnum():
        virtual_key = ord(trigger.upper())
    else:
        try:
            virtual_key = _WINDOWS_NAMED_KEYS[trigger]
        except KeyError as error:
            raise ValueError(f"Unsupported Windows hotkey key: {trigger}") from error

    modifiers = 0
    for part in parts:
        modifiers |= _WINDOWS_MODIFIERS.get(part, 0)
    log_event(
        logger,
        logging.DEBUG,
        "hotkey.translated_for_windows",
        input=hotkey,
        modifiers=modifiers,
        virtual_key=virtual_key,
    )
    return modifiers, virtual_key


def from_windows_hotkey(modifiers: int, virtual_key: int) -> str:
    """Build the stable display name for a shortcut recorded by Windows."""
    parts = [name for name in _MODIFIER_ORDER if modifiers & _WINDOWS_MODIFIERS[name]]
    if ord("0") <= virtual_key <= ord("9") or ord("A") <= virtual_key <= ord("Z"):
        trigger = chr(virtual_key).lower()
    else:
        trigger = _WINDOWS_KEY_NAMES.get(virtual_key, "")
    return "+".join([*parts, trigger]) if trigger else ""
