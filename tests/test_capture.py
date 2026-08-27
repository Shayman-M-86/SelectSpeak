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


def test_resolve_capture_unresolved_does_not_read_clipboard() -> None:
    """A copy that was sent but never confirmed must not be spoken as if it

    were the pre-capture clipboard contents - the target may still finish
    the copy after we stop waiting for it.
    """
    clipboard_reads = 0

    def read_clipboard() -> str:
        nonlocal clipboard_reads
        clipboard_reads += 1
        return "stale clipboard text"

    result = resolve_capture(
        "",
        read_clipboard,
        allow_clipboard_fallback=True,
        capture_unresolved=True,
    )

    assert result.source == "unresolved"
    assert result.raw_text == ""
    assert clipboard_reads == 0


def test_resolve_capture_prefers_selection_even_when_unresolved_flag_set() -> None:
    result = resolve_capture(
        "selected text",
        lambda: "clipboard text",
        allow_clipboard_fallback=True,
        capture_unresolved=True,
    )

    assert result.source == "selection"
    assert result.raw_text == "selected text"
