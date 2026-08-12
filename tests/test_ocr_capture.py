from selectspeak.input.ocr_capture import wait_for_clipboard_update


def test_wait_for_clipboard_update_ignores_unchanged_sequence() -> None:
    sequences = iter((10, 10, 11))
    reads: list[bool] = []

    result = wait_for_clipboard_update(
        10,
        lambda: next(sequences),
        lambda: reads.append(True) or "Recognized text",
        timeout_seconds=1.0,
        poll_seconds=0.0,
    )

    assert result == "Recognized text"
    assert reads == [True]


def test_wait_for_clipboard_update_waits_past_non_text_updates() -> None:
    sequences = iter((21, 22))
    clipboard = iter((None, "OCR result"))

    result = wait_for_clipboard_update(
        20,
        lambda: next(sequences),
        lambda: next(clipboard),
        timeout_seconds=1.0,
        poll_seconds=0.0,
    )

    assert result == "OCR result"
