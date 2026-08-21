from collections.abc import Callable
from typing import Any, cast

from selectspeak.app import application as application_module
from selectspeak.app import voices as voices_module
from selectspeak.app.application import (
    SelectSpeakApp,
    is_repeat_of_active_speech,
    should_stop_clipboard_speech_immediately,
    was_speaking_at,
)
from selectspeak.app.voices import VoiceController, confirm_supertonic_install
from selectspeak.config import AppConfig


def test_supertonic_install_confirmation_uses_windows_yes_result(monkeypatch) -> None:
    class User32:
        @staticmethod
        def MessageBoxW(*_arguments: object) -> int:
            return voices_module.MESSAGE_BOX_YES

    class WindowsLibraries:
        user32 = User32()

    monkeypatch.setattr(voices_module.ctypes, "windll", WindowsLibraries(), raising=False)

    assert confirm_supertonic_install()


def test_supertonic_install_is_required_if_either_payload_is_missing(monkeypatch) -> None:
    controller = object.__new__(VoiceController)
    controller._config = AppConfig()
    monkeypatch.setattr(voices_module, "supertonic_dependencies_are_installed", lambda: True)
    monkeypatch.setattr(voices_module, "supertonic_model_is_installed", lambda _voice: False)

    assert controller._install_required()

    monkeypatch.setattr(voices_module, "supertonic_model_is_installed", lambda _voice: True)
    assert not controller._install_required()


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
    assert should_stop_clipboard_speech_immediately(speaking=True, source="clipboard_fallback")
    assert not should_stop_clipboard_speech_immediately(speaking=True, source="selection")


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

        def close(self) -> None:
            pass

    class Voices:
        def __init__(self, speaker: Speaker) -> None:
            self.speaker = speaker

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
    setattr(app, "_voices", Voices(speaker))
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
        loading_activity = ""

        @staticmethod
        def call_soon(callback: Callable[[], None]) -> None:
            callback()

        @classmethod
        def show_backend_loading(cls, activity: str) -> None:
            cls.loading_activity = activity

    class Voices:
        """Stand in for VoiceController, mid-switch."""

        switching = True
        activity = "installing"

    app = SelectSpeakApp()
    setattr(app, "_player", Player())
    setattr(app, "_voices", Voices())

    assert app._on_hotkey_activation()
    assert Player.loading_activity == "installing"


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

        def close(self) -> None:
            pass

    class Voices:
        def __init__(self, speaker: Speaker) -> None:
            self.speaker = speaker

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
    setattr(app, "_voices", Voices(new_speaker))
    setattr(app, "_player", Player())
    app._session.start(old_speaker, 1, "Active speech", "selection", 1.0)

    app.stop()

    assert old_speaker.stop_count == 1
    assert new_speaker.stop_count == 0


def test_voice_controller_creates_owns_and_closes_initial_speaker(monkeypatch) -> None:
    class Speaker:
        close_count = 0

        def close(self) -> None:
            self.close_count += 1

    speaker = Speaker()
    monkeypatch.setattr(voices_module, "create_speaker", lambda *_args: speaker)
    monkeypatch.setattr(voices_module, "speaker_backend", lambda _speaker: "test")
    monkeypatch.setattr(VoiceController, "publish_options", lambda *_args: None)
    controller = VoiceController(
        AppConfig(),
        cast(Any, object()),
        word_callback=lambda *_args: None,
        debug_callback=lambda _event: None,
        on_activated=lambda *_args: None,
        on_stop_playback=lambda: None,
        on_shutdown_requested=lambda: None,
    )

    controller.start()

    assert controller.speaker is speaker
    assert controller.backend == "test"
    controller.close()
    controller.close()
    assert speaker.close_count == 1


def test_shutdown_is_ordered_idempotent_and_continues_after_cleanup_failure(monkeypatch) -> None:
    events: list[str] = []

    class Resource:
        def __init__(self, name: str, method: str, *, fail: bool = False) -> None:
            self.name = name
            self.fail = fail
            setattr(self, method, self.run)

        def run(self) -> None:
            events.append(self.name)
            if self.fail:
                raise RuntimeError(f"{self.name} failed")

    class Speaker:
        def speak(self, text: str) -> int:
            del text
            return 1

        def stop(self) -> None:
            events.append("active_playback")

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

        def wait_until_done(self, generation: int) -> bool:
            del generation
            return False

        def close(self) -> None:
            pass

    app = SelectSpeakApp()
    speaker = Speaker()
    app._session.start(speaker, 1, "Active speech", "selection", 1.0)
    setattr(app, "_hotkeys", Resource("hotkeys", "close", fail=True))
    setattr(app, "_ocr_capture", Resource("ocr", "stop"))
    setattr(app, "_voices", Resource("voices", "close"))
    setattr(app, "_tray", Resource("tray", "stop"))
    setattr(app, "_player", Resource("player", "destroy"))
    monkeypatch.setattr(
        application_module,
        "shutdown_native_bridge",
        lambda: events.append("native_bridge"),
    )

    app.shutdown()
    app.shutdown()

    assert events == [
        "hotkeys",
        "ocr",
        "active_playback",
        "voices",
        "tray",
        "player",
        "native_bridge",
    ]


def test_shutdown_after_partial_startup_still_releases_native_bridge(monkeypatch) -> None:
    events: list[str] = []
    app = SelectSpeakApp()
    monkeypatch.setattr(
        application_module,
        "shutdown_native_bridge",
        lambda: events.append("native_bridge"),
    )

    app.shutdown()

    assert events == ["native_bridge"]
