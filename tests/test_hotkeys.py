from selectspeak.keymap import (
    build_hotkey,
    normalize_key,
    to_pynput_hotkey,
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


def test_to_pynput_hotkey_translates_modifiers_and_named_keys() -> None:
    assert to_pynput_hotkey("alt+s") == "<alt>+s"
    assert to_pynput_hotkey("ctrl+alt+h") == "<ctrl>+<alt>+h"
    assert to_pynput_hotkey("shift+f8") == "<shift>+<f8>"


def test_to_windows_hotkey_returns_modifier_groups_and_trigger_vk() -> None:
    modifier_groups, trigger_vk = to_windows_hotkey("alt+s")

    assert 0x12 in modifier_groups[0]
    assert trigger_vk == ord("S")
