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
from selectspeak.speech import SpeechStarted, SpeechTerminal, SpeechWord, TerminalStatus


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


def test_clipboard_fallback_survives_a_capture_that_emptied_the_clipboard() -> None:
    """Capturing a selection can empty the clipboard while probing for one.

    The native layer copies the original text out before that happens, so the
    fallback must use its snapshot rather than re-reading the clipboard the
    probe just cleared.
    """

    class Hotkeys:
        hotkey = "alt+s"
        capturing = False

    class Clipboard:
        read_count = 0

        def read_text(self) -> str:
            # What a re-read would see after the capture probe cleared it.
            self.read_count += 1
            return ""

    class Speaker:
        spoken: list[str] = []

        def speak(self, request_id: int, text: str, callback: Callable[..., None]) -> bool:
            del request_id, callback
            self.spoken.append(text)
            return True

        def stop(self) -> None:
            pass

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

        def close(self) -> None:
            pass

    class Voices:
        switching = False
        activity = ""

        def __init__(self, speaker: Speaker) -> None:
            self.speaker = speaker

    class Player:
        @staticmethod
        def call_soon(callback: Callable[[], None]) -> None:
            callback()

        @staticmethod
        def set_playback(**_values: object) -> None:
            pass

        @staticmethod
        def reset_speech_debug() -> None:
            pass

        @staticmethod
        def show() -> None:
            pass

    app = SelectSpeakApp()
    speaker = Speaker()
    clipboard = Clipboard()
    setattr(app, "_hotkeys", Hotkeys())
    setattr(app, "_clipboard", clipboard)
    setattr(app, "_voices", Voices(speaker))
    setattr(app, "_player", Player())
    setattr(app, "_clipboard_mode", True)

    app._on_hotkey("", 10.0, "Text the probe erased.")

    assert speaker.spoken == ["Text the probe erased."]
    assert clipboard.read_count == 0


def test_clipboard_fallback_is_ignored_when_text_is_selected() -> None:
    class Hotkeys:
        hotkey = "alt+s"
        capturing = False

    class Clipboard:
        @staticmethod
        def read_text() -> str:
            return "Clipboard text."

    class Speaker:
        spoken: list[str] = []

        def speak(self, request_id: int, text: str, callback: Callable[..., None]) -> bool:
            del request_id, callback
            self.spoken.append(text)
            return True

        def stop(self) -> None:
            pass

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

        def close(self) -> None:
            pass

    class Voices:
        switching = False
        activity = ""

        def __init__(self, speaker: Speaker) -> None:
            self.speaker = speaker

    class Player:
        @staticmethod
        def call_soon(callback: Callable[[], None]) -> None:
            callback()

        @staticmethod
        def set_playback(**_values: object) -> None:
            pass

        @staticmethod
        def reset_speech_debug() -> None:
            pass

        @staticmethod
        def show() -> None:
            pass

    app = SelectSpeakApp()
    speaker = Speaker()
    setattr(app, "_hotkeys", Hotkeys())
    setattr(app, "_clipboard", Clipboard())
    setattr(app, "_voices", Voices(speaker))
    setattr(app, "_player", Player())
    setattr(app, "_clipboard_mode", True)

    app._on_hotkey("Selected sentence.", 10.0, "Clipboard snapshot.")

    assert speaker.spoken == ["Selected sentence."]


def test_clipboard_snapshot_is_unused_when_fallback_is_disabled() -> None:
    class Hotkeys:
        hotkey = "alt+s"
        capturing = False

    class Clipboard:
        @staticmethod
        def read_text() -> str:
            return "Clipboard text."

    class Speaker:
        spoken: list[str] = []

        def speak(self, request_id: int, text: str, callback: Callable[..., None]) -> bool:
            del request_id, callback
            self.spoken.append(text)
            return True

        def stop(self) -> None:
            pass

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

        def close(self) -> None:
            pass

    class Voices:
        switching = False
        activity = ""

        def __init__(self, speaker: Speaker) -> None:
            self.speaker = speaker

    class Player:
        shown = False

        @staticmethod
        def call_soon(callback: Callable[[], None]) -> None:
            callback()

        @staticmethod
        def set_playback(**_values: object) -> None:
            pass

        @staticmethod
        def reset_speech_debug() -> None:
            pass

        @classmethod
        def show(cls) -> None:
            cls.shown = True

    app = SelectSpeakApp()
    speaker = Speaker()
    setattr(app, "_hotkeys", Hotkeys())
    setattr(app, "_clipboard", Clipboard())
    setattr(app, "_voices", Voices(speaker))
    setattr(app, "_player", Player())
    setattr(app, "_clipboard_mode", False)

    app._on_hotkey("", 10.0, "Clipboard snapshot.")

    assert speaker.spoken == []


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

        def speak(self, request_id: int, text: str, callback: Callable[..., None]) -> bool:
            del request_id, text, callback
            return True

        def stop(self) -> None:
            self.stop_count += 1

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

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


def test_clipboard_fallback_setting_does_not_bypass_selection_capture() -> None:
    class Voices:
        switching = False

    app = SelectSpeakApp(AppConfig(clipboard_mode=True))
    setattr(app, "_voices", Voices())

    assert not app._on_hotkey_activation()


def test_application_allocates_request_ids_and_consumes_ordered_events() -> None:
    class Speaker:
        request_ids: list[int] = []

        def speak(self, request_id: int, text: str, callback: Callable[..., None]) -> bool:
            self.request_ids.append(request_id)
            callback(SpeechStarted(request_id))
            callback(SpeechWord(request_id, text, 0, 4))
            callback(SpeechTerminal(request_id, TerminalStatus.COMPLETED))
            return True

    class Voices:
        switching = False

        def __init__(self, speaker: Speaker) -> None:
            self.speaker = speaker

    class Player:
        highlights: list[tuple[int, int]] = []

        @staticmethod
        def call_soon(callback: Callable[[], None]) -> None:
            callback()

        @staticmethod
        def reset_speech_debug() -> None:
            pass

        @staticmethod
        def set_playback(**_values: object) -> None:
            pass

        @classmethod
        def highlight_word(cls, position: int, length: int) -> None:
            cls.highlights.append((position, length))

    app = SelectSpeakApp()
    speaker = Speaker()
    setattr(app, "_voices", Voices(speaker))
    setattr(app, "_player", Player())

    app._begin_speech("Read this", source="selection")
    app._begin_speech("Read that", source="selection")

    assert speaker.request_ids == [1, 2]
    assert Player.highlights == [(0, 4), (0, 4)]
    assert app._session.snapshot().terminal_status is TerminalStatus.COMPLETED


def test_played_word_delivery_is_queued_after_request_validation() -> None:
    class Speaker:
        def speak(self, request_id: int, text: str, callback: Callable[..., None]) -> bool:
            callback(SpeechStarted(request_id))
            callback(SpeechWord(request_id, text, 0, 4))
            return True

        def stop(self) -> None:
            pass

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

        def close(self) -> None:
            pass

    class Voices:
        switching = False

        def __init__(self, speaker: Speaker) -> None:
            self.speaker = speaker

    class Player:
        callbacks: list[Callable[[], None]] = []
        highlights: list[tuple[int, int]] = []

        @classmethod
        def call_soon(cls, callback: Callable[[], None]) -> None:
            cls.callbacks.append(callback)

        @staticmethod
        def reset_speech_debug() -> None:
            pass

        @staticmethod
        def set_playback(**_values: object) -> None:
            pass

        @classmethod
        def highlight_word(cls, position: int, length: int) -> None:
            cls.highlights.append((position, length))

    app = SelectSpeakApp()
    speaker = Speaker()
    setattr(app, "_voices", Voices(speaker))
    setattr(app, "_player", Player())

    app._begin_speech("Read this", source="selection")

    assert Player.highlights == []
    queued_after_current_word = len(Player.callbacks)
    app._on_speech_event(speaker, "Stale", "selection", SpeechWord(2, "Stale", 0, 5))
    assert len(Player.callbacks) == queued_after_current_word

    for callback in Player.callbacks:
        callback()
    assert Player.highlights == [(0, 4)]


def test_stop_targets_the_speaker_that_started_the_active_request() -> None:
    class Speaker:
        def __init__(self) -> None:
            self.stop_count = 0

        def stop(self) -> None:
            self.stop_count += 1

        def speak(self, request_id: int, text: str, callback: Callable[..., None]) -> bool:
            del request_id, text, callback
            return True

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

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
        def speak(self, request_id: int, text: str, callback: Callable[..., None]) -> bool:
            del request_id, text, callback
            return True

        def stop(self) -> None:
            events.append("active_playback")

        def pause(self) -> None:
            pass

        def resume(self) -> None:
            pass

        def close(self) -> None:
            pass

    app = SelectSpeakApp(AppConfig(clipboard_mode=True))
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
