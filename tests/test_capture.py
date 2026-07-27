from selectspeak.capture import resolve_capture


def test_resolve_capture_prefers_selected_text() -> None:
    clipboard_reads = 0

    def read_clipboard() -> str:
        nonlocal clipboard_reads
        clipboard_reads += 1
        return "clipboard text"

    result = resolve_capture(
        " selected text ",
        read_clipboard,
        force_clipboard=False,
    )

    assert result.source == "selection"
    assert result.text == "selected text"
    assert clipboard_reads == 0


def test_resolve_capture_falls_back_when_selection_is_empty() -> None:
    result = resolve_capture("", lambda: "clipboard text", force_clipboard=False)

    assert result.source == "clipboard_fallback"
    assert result.text == "clipboard text"


def test_resolve_capture_falls_back_for_whitespace_selection() -> None:
    result = resolve_capture(" \n ", lambda: "clipboard text", force_clipboard=False)

    assert result.source == "clipboard_fallback"
    assert result.text == "clipboard text"


def test_resolve_capture_honors_forced_clipboard_mode() -> None:
    result = resolve_capture(
        "selected text",
        lambda: "clipboard text",
        force_clipboard=True,
    )

    assert result.source == "clipboard"
    assert result.text == "clipboard text"
