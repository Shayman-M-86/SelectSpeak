from selectspeak.input.keymap import normalize_key, to_windows_hotkey


def test_normalize_key_collapses_left_and_right_modifiers() -> None:
    assert normalize_key("Left Ctrl") == "ctrl"
    assert normalize_key("right alt") == "alt"


def test_to_windows_hotkey_translates_modifiers_and_letter() -> None:
    assert to_windows_hotkey("alt+s") == (0x0001, ord("S"))


def test_to_windows_hotkey_translates_named_keys() -> None:
    assert to_windows_hotkey("ctrl+shift+f8") == (0x0006, 0x77)


def test_to_windows_hotkey_rejects_a_modifier_only_combination() -> None:
    """The settings window records these, but they cannot be bound."""
    import pytest

    with pytest.raises(ValueError):
        to_windows_hotkey("ctrl+alt")
