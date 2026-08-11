from selectspeak.keymap import (
    build_hotkey,
    from_windows_hotkey,
    normalize_key,
    to_windows_hotkey,
)


def test_normalize_key_collapses_left_and_right_modifiers() -> None:
    assert normalize_key("Left Ctrl") == "ctrl"
    assert normalize_key("right alt") == "alt"


def test_build_hotkey_orders_modifiers_and_key() -> None:
    keys = {"s", "left shift", "left alt"}

    assert build_hotkey(keys) == "alt+shift+s"


def test_build_hotkey_rejects_modifier_only_combinations() -> None:
    assert build_hotkey({"left ctrl", "left alt"}) == ""


def test_to_windows_hotkey_translates_modifiers_and_letter() -> None:
    assert to_windows_hotkey("alt+s") == (0x0001, ord("S"))


def test_to_windows_hotkey_translates_named_keys() -> None:
    assert to_windows_hotkey("ctrl+shift+f8") == (0x0006, 0x77)


def test_from_windows_hotkey_builds_stable_display_name() -> None:
    assert from_windows_hotkey(0x0006, 0x77) == "ctrl+shift+f8"
