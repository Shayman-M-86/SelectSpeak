import threading
from types import SimpleNamespace
from typing import Any

import pytest

from selectspeak.config import AppConfig
from selectspeak.speech.backends import natural as natural_backend
from selectspeak.speech.backends.natural import (
    NaturalVoice,
    NaturalVoiceEngine,
    NaturalVoiceError,
    NaturalVoiceSpeaker,
)
from selectspeak.speech.pipeline import GenerationStatistics
from selectspeak.speech.playback import PlaybackController


def test_choose_voice_matches_name_locale_display_name_or_path() -> None:
    voices = [
        NaturalVoice("C:/voices/Aria", "en-US-Aria", "en-US", "Microsoft Aria"),
        NaturalVoice("C:/voices/Jenny", "en-AU-Jenny", "en-AU", "Microsoft Jenny"),
    ]

    assert NaturalVoiceEngine._choose_voice(voices, "jenny") == voices[1]
    assert NaturalVoiceEngine._choose_voice(voices, "EN-US") == voices[0]
    assert NaturalVoiceEngine._choose_voice(voices, "missing") == voices[0]


def test_ordered_voices_keeps_fallbacks_after_preferred_matches() -> None:
    voices = [
        NaturalVoice("C:/Ava", "Microsoft Ava HD", "en-US", "Ava"),
        NaturalVoice("C:/Aria", "Microsoft Aria", "en-US", "Aria"),
        NaturalVoice("C:/Sonia", "Microsoft Sonia", "en-GB", "Sonia"),
    ]

    assert NaturalVoiceEngine._ordered_voices(voices, "Aria") == [
        voices[1],
        voices[0],
        voices[2],
    ]


def test_engine_initializes_the_preferred_installed_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = [
        NaturalVoice("C:/WindowsApps/AvaHD", "Microsoft Ava", "en-US", "Ava"),
        NaturalVoice("C:/WindowsApps/Aria", "Microsoft Aria", "en-US", "Aria"),
    ]
    initialized_arguments: list[tuple[Any, ...]] = []

    class FakeFunction:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, *args: Any) -> int | None:
            if self.name == "ss_voice_list":
                callback = args[0]
                for voice in installed:
                    callback(
                        voice.package_path,
                        voice.name.encode(),
                        voice.locale.encode(),
                        voice.display_name.encode(),
                        None,
                    )
                return len(installed)
            if self.name == "ss_voice_initialize":
                initialized_arguments.append(args)
                return 0
            return None if self.name == "ss_voice_shutdown" else 0

    class FakeDll:
        def __init__(self) -> None:
            for name in (
                "ss_voice_list",
                "ss_voice_initialize",
                "ss_voice_set_audio_callback",
                "ss_voice_set_word_callback",
                "ss_voice_speak",
                "ss_voice_stop",
                "ss_voice_shutdown",
                "ss_voice_last_error",
            ):
                setattr(self, name, FakeFunction(name))

    fake_dll = FakeDll()
    monkeypatch.setattr(
        natural_backend,
        "get_native_bridge",
        lambda _configured: SimpleNamespace(library=fake_dll),
    )
    config = AppConfig(preferred_voice_match="Aria").speech
    engine = NaturalVoiceEngine(config, lambda _data: None, lambda *_: None)

    assert engine.voice == installed[1]
    assert engine.available_voices == (installed[1], installed[0])
    assert initialized_arguments == [
        (installed[1].package_path, installed[1].name.encode("utf-8"))
    ]
    engine.close()


def test_engine_requires_an_installed_windows_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeFunction:
        def __init__(self, result: int | None = 0) -> None:
            self.result = result

        def __call__(self, *_args: Any) -> int | None:
            return self.result

    class FakeDll:
        ss_voice_list = FakeFunction()
        ss_voice_initialize = FakeFunction()
        ss_voice_set_audio_callback = FakeFunction(None)
        ss_voice_set_word_callback = FakeFunction(None)
        ss_voice_speak = FakeFunction()
        ss_voice_stop = FakeFunction()
        ss_voice_shutdown = FakeFunction(None)
        ss_voice_last_error = FakeFunction()

    monkeypatch.setattr(
        natural_backend,
        "get_native_bridge",
        lambda _configured: SimpleNamespace(library=FakeDll()),
    )

    with pytest.raises(NaturalVoiceError, match="No Windows Natural Voices are installed"):
        NaturalVoiceEngine(AppConfig().speech, lambda _data: None, lambda *_: None)


def test_select_voice_refreshes_packages_installed_after_engine_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = [NaturalVoice("C:/WindowsApps/AvaHD", "Microsoft Ava", "en-US", "Ava")]
    initialized_paths: list[str] = []

    class FakeFunction:
        def __init__(self, implementation: Any) -> None:
            self.implementation = implementation

        def __call__(self, *args: Any) -> Any:
            return self.implementation(*args)

    def list_voices(callback: Any, _context: Any) -> int:
        for voice in installed:
            callback(
                voice.package_path,
                voice.name.encode(),
                voice.locale.encode(),
                voice.display_name.encode(),
                None,
            )
        return len(installed)

    def initialize(package_path: str, _voice_name: bytes) -> int:
        initialized_paths.append(package_path)
        return 0

    class FakeDll:
        ss_voice_list = FakeFunction(list_voices)
        ss_voice_initialize = FakeFunction(initialize)
        ss_voice_set_audio_callback = FakeFunction(lambda *_args: None)
        ss_voice_set_word_callback = FakeFunction(lambda *_args: None)
        ss_voice_speak = FakeFunction(lambda *_args: 0)
        ss_voice_stop = FakeFunction(lambda: 0)
        ss_voice_shutdown = FakeFunction(lambda: None)
        ss_voice_last_error = FakeFunction(lambda *_args: 1)

    monkeypatch.setattr(
        natural_backend,
        "get_native_bridge",
        lambda _configured: SimpleNamespace(library=FakeDll()),
    )
    engine = NaturalVoiceEngine(AppConfig().speech, lambda _data: None, lambda *_: None)

    new_voice = NaturalVoice(
        "C:/WindowsApps/AndrewHD",
        "Microsoft Andrew",
        "en-US",
        "Andrew",
    )
    installed.append(new_voice)

    assert engine.select_voice(new_voice.package_path) == new_voice
    assert engine.voice == new_voice
    assert new_voice in engine.available_voices
    assert initialized_paths == ["C:/WindowsApps/AvaHD", new_voice.package_path]


class _FakePlayer:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self._fed_bytes = 0

    @property
    def fed_bytes(self) -> int:
        return self._fed_bytes

    @property
    def buffered_seconds(self) -> float:
        return self._fed_bytes / 48_000

    def start(self) -> None:
        self.events.append(("start", None))

    def feed(self, data: bytes) -> None:
        self.events.append(("feed", data))
        self._fed_bytes += len(data)

    def feed_silence(self, seconds: float) -> None:
        self.events.append(("silence", seconds))
        self._fed_bytes += round(seconds * 48_000)

    def add_boundary(
        self,
        offset_ticks: int,
        position: int,
        length: int,
        *,
        base_byte_offset: int = 0,
    ) -> None:
        self.events.append(
            (
                "boundary",
                (offset_ticks, position, length, base_byte_offset),
            )
        )

    def finish(self) -> None:
        self.events.append(("finish", None))


class _FakeEngine:
    def __init__(self, speaker: NaturalVoiceSpeaker) -> None:
        self.speaker = speaker
        self.spoken: list[str] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)
        self.speaker._on_engine_boundary(0, 0, len(text.split()[0]))
        self.speaker._on_engine_audio(b"\x01\x00" * len(text))


def test_natural_voice_uses_the_shared_persistent_stream() -> None:
    text = (
        "A deliberately long technical statement that must cross the ordinary "
        "chunk limit without receiving an artificial pause in the middle. "
        "The second sentence follows."
    )
    speaker = object.__new__(NaturalVoiceSpeaker)
    speaker._config = AppConfig(structure_pause_seconds=0.1).speech
    speaker._playback = PlaybackController()
    request, _active = speaker._playback.submit(1, text, lambda _event: None)
    assert speaker._playback.next_request() == request
    speaker._request_text = ""
    speaker._segment_text_offset = 0
    speaker._segment_audio_base = 0
    speaker._generation_statistics = GenerationStatistics()
    player = _FakePlayer()
    speaker._player = player
    engine = _FakeEngine(speaker)
    speaker._engine = engine

    speaker._speak_request(request)

    assert len(engine.spoken) == 2
    assert [event for event, _ in player.events].count("start") == 1
    assert [event for event, _ in player.events].count("finish") == 1
    assert [value for event, value in player.events if event == "silence"] == [pytest.approx(0.1)]
    boundary_positions = [value[1] for event, value in player.events if event == "boundary"]
    assert boundary_positions == sorted(boundary_positions)


def test_natural_voice_close_cancels_joins_and_releases_engine() -> None:
    events: list[str] = []

    class Player:
        def request_stop(self) -> None:
            events.append("player.request_stop")

        def wait_until_stopped(self) -> None:
            events.append("player.wait_until_stopped")

    class Engine:
        def stop(self) -> None:
            events.append("engine.stop")

        def close(self) -> None:
            events.append("engine.close")

    class Worker:
        def join(self) -> None:
            events.append("worker.join")

    speaker = object.__new__(NaturalVoiceSpeaker)
    speaker._close_lock = threading.Lock()
    speaker._closed = False
    speaker._playback = PlaybackController()
    request, _active = speaker._playback.submit(1, "Read this", lambda _event: None)
    assert speaker._playback.next_request() == request
    speaker._player = Player()
    speaker._engine = Engine()
    speaker._thread = Worker()

    speaker.close()
    speaker.close()

    assert events == [
        "player.request_stop",
        "engine.stop",
        "player.wait_until_stopped",
        "worker.join",
        "engine.close",
    ]
