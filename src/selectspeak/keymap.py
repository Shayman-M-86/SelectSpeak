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
_PYNPUT_MODIFIERS = {
    "ctrl": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
    "windows": "<cmd>",
}
_WINDOWS_MODIFIER_VKS = {
    "ctrl": frozenset((0x11, 0xA2, 0xA3)),
    "shift": frozenset((0x10, 0xA0, 0xA1)),
    "alt": frozenset((0x12, 0xA4, 0xA5)),
    "windows": frozenset((0x5B, 0x5C)),
}
_WINDOWS_NAMED_VKS = {
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
_WINDOWS_NAMED_VKS.update({f"f{number}": 0x6F + number for number in range(1, 25)})


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


def to_pynput_hotkey(hotkey: str) -> str:
    """Translate ``alt+s`` style configuration to pynput's parser syntax."""
    parts = [normalize_key(part.strip()) for part in hotkey.split("+")]
    translated = []
    for part in parts:
        if part in _PYNPUT_MODIFIERS:
            translated.append(_PYNPUT_MODIFIERS[part])
        elif len(part) == 1:
            translated.append(part)
        else:
            translated.append(f"<{part}>")
    result = "+".join(translated)
    log_event(
        logger,
        logging.DEBUG,
        "hotkey.translated_for_pynput",
        input=hotkey,
        output=result,
    )
    return result


def to_windows_hotkey(
    hotkey: str,
) -> tuple[tuple[frozenset[int], ...], int]:
    """Return required modifier VK groups and the trigger key's Windows VK."""
    parts = [normalize_key(part.strip()) for part in hotkey.split("+")]
    modifier_groups = tuple(
        _WINDOWS_MODIFIER_VKS[part] for part in parts if part in _MODIFIER_NAMES
    )
    ordinary_keys = [part for part in parts if part not in _MODIFIER_NAMES]
    if len(ordinary_keys) != 1:
        raise ValueError("A global hotkey must contain exactly one trigger key")

    trigger = ordinary_keys[0]
    if len(trigger) == 1:
        trigger_vk = ord(trigger.upper())
    else:
        try:
            trigger_vk = _WINDOWS_NAMED_VKS[trigger]
        except KeyError as error:
            raise ValueError(f"Unsupported global hotkey key: {trigger}") from error

    log_event(
        logger,
        logging.DEBUG,
        "hotkey.translated_for_windows",
        input=hotkey,
        modifier_vks=[sorted(group) for group in modifier_groups],
        trigger_vk=trigger_vk,
    )
    return modifier_groups, trigger_vk
