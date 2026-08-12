from collections.abc import Callable

from selectspeak.app import (
    SelectSpeakApp,
    is_repeat_of_active_speech,
    should_stop_clipboard_speech_immediately,
    was_speaking_at,
)


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


def test_hotkey_uses_speech_state_at_activation_before_capture_delay() -> None:
    assert was_speaking_at(12.5, speech_started_at=10.0, speech_ended_at=13.0)
    assert not was_speaking_at(13.5, speech_started_at=10.0, speech_ended_at=13.0)


def test_clipboard_speech_stops_before_selection_capture() -> None:
    assert should_stop_clipboard_speech_immediately(
        speaking=True, source="clipboard_fallback"
    )
    assert not should_stop_clipboard_speech_immediately(
        speaking=True, source="selection"
    )


def test_delayed_clipboard_fallback_stops_speech_active_at_keypress() -> None:
    class Hotkeys:
        hotkey = "alt+s"
        capturing = False

    class Clipboard:
        @staticmethod
        def read_text() -> str:
            return "Clipboard fallback sentence."

    class Speaker:
        stop_count = 0

        def speak(self, text: str) -> int:
            del text
            return 1

        def stop(self) -> None:
            self.stop_count += 1

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

        def wait_until_done(self, generation: int) -> bool:
            del generation
            return True

    class Player:
        @staticmethod
        def call_soon(callback: Callable[[], None]) -> None:
            callback()

        @staticmethod
        def set_playback(**_values: object) -> None:
            pass

    app = SelectSpeakApp()
    speaker = Speaker()
    setattr(app, "_hotkeys", Hotkeys())
    setattr(app, "_clipboard", Clipboard())
    setattr(app, "_speaker", speaker)
    setattr(app, "_player", Player())
    app._session.start(
        speaker,
        1,
        "Clipboard fallback sentence.",
        "clipboard_fallback",
        10.0,
    )
    app._session.stop(speaker, 11.0)

    app._on_hotkey("", activated_at=10.5)

    assert speaker.stop_count == 1


def test_hotkey_is_consumed_while_voice_backend_is_loading() -> None:
    class Player:
        loading_shown = False

        @staticmethod
        def call_soon(callback: Callable[[], None]) -> None:
            callback()

        @classmethod
        def show_backend_loading(cls) -> None:
            cls.loading_shown = True

    app = SelectSpeakApp()
    setattr(app, "_player", Player())
    app._backend_switching = True

    assert app._on_hotkey_activation()
    assert Player.loading_shown


def test_stop_targets_the_speaker_that_started_the_active_request() -> None:
    class Speaker:
        def __init__(self) -> None:
            self.stop_count = 0

        def stop(self) -> None:
            self.stop_count += 1

        def speak(self, text: str) -> int:
            del text
            return 1

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

        def wait_until_done(self, generation: int) -> bool:
            del generation
            return True

    class Player:
        @staticmethod
        def call_soon(callback: Callable[[], None]) -> None:
            callback()

        @staticmethod
        def set_playback(**_values: object) -> None:
            pass

    app = SelectSpeakApp()
    old_speaker = Speaker()
    new_speaker = Speaker()
    setattr(app, "_speaker", new_speaker)
    setattr(app, "_player", Player())
    app._session.start(old_speaker, 1, "Active speech", "selection", 1.0)

    app.stop()

    assert old_speaker.stop_count == 1
    assert new_speaker.stop_count == 0
