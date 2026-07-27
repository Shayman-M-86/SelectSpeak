from selectspeak.keymap import (
    build_hotkey,
    normalize_key,
    to_autohotkey_hotkey,
)


def test_normalize_key_collapses_left_and_right_modifiers() -> None:
    assert normalize_key("Left Ctrl") == "ctrl"
    assert normalize_key("right alt") == "alt"


def test_build_hotkey_orders_modifiers_and_key() -> None:
    keys = {"s", "left shift", "left alt"}

    assert build_hotkey(keys) == "alt+shift+s"


def test_build_hotkey_rejects_modifier_only_combinations() -> None:
    assert build_hotkey({"left ctrl", "left alt"}) == ""


def test_to_autohotkey_hotkey_suppresses_the_complete_chord() -> None:
    hotkey, trigger = to_autohotkey_hotkey("alt+s")

    assert hotkey == "$!s"
    assert trigger == "s"


def test_to_autohotkey_hotkey_translates_named_keys() -> None:
    assert to_autohotkey_hotkey("ctrl+shift+f8") == ("$^+F8", "F8")
