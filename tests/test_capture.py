from selectspeak.capture import fresh_clipboard_text


def test_fresh_clipboard_text_accepts_new_selection() -> None:
    assert fresh_clipboard_text("old clipboard", "selected text") == "selected text"


def test_fresh_clipboard_text_rejects_stale_clipboard_value() -> None:
    assert fresh_clipboard_text("stale value", "stale value") is None


def test_fresh_clipboard_text_rejects_empty_copy() -> None:
    assert fresh_clipboard_text("old clipboard", "") is None
