from selectspeak.input.capture import resolve_capture


def test_resolve_capture_prefers_selected_text() -> None:
    clipboard_reads = 0

    def read_clipboard() -> str:
        nonlocal clipboard_reads
        clipboard_reads += 1
        return "clipboard text"

    result = resolve_capture(
        " selected text ",
        read_clipboard,
        allow_clipboard_fallback=True,
    )

    assert result.source == "selection"
    assert result.raw_text == " selected text "
    assert clipboard_reads == 0


def test_resolve_capture_falls_back_when_selection_is_empty() -> None:
    result = resolve_capture("", lambda: "clipboard text", allow_clipboard_fallback=True)

    assert result.source == "clipboard_fallback"
    assert result.raw_text == "clipboard text"


def test_resolve_capture_falls_back_for_whitespace_selection() -> None:
    result = resolve_capture(" \n ", lambda: "clipboard text", allow_clipboard_fallback=True)

    assert result.source == "clipboard_fallback"
    assert result.raw_text == "clipboard text"


def test_resolve_capture_does_not_read_clipboard_when_fallback_is_disabled() -> None:
    clipboard_reads = 0

    def read_clipboard() -> str:
        nonlocal clipboard_reads
        clipboard_reads += 1
        return "clipboard text"

    result = resolve_capture(
        "",
        read_clipboard,
        allow_clipboard_fallback=False,
    )

    assert result.source == "empty"
    assert result.raw_text == ""
    assert clipboard_reads == 0
