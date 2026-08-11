from selectspeak.app import is_repeat_of_active_speech


def test_same_text_while_speaking_requests_stop() -> None:
    assert is_repeat_of_active_speech(
        speaking=True,
        active_text="Read this text.",
        captured_text="Read this text.",
    )


def test_same_text_after_stop_requests_replay() -> None:
    assert not is_repeat_of_active_speech(
        speaking=False,
        active_text="Read this text.",
        captured_text="Read this text.",
    )


def test_different_text_while_speaking_replaces_current_reading() -> None:
    assert not is_repeat_of_active_speech(
        speaking=True,
        active_text="Old selection",
        captured_text="New selection",
    )
