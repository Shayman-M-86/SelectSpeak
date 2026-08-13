from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from selectspeak.config import AppConfig
from selectspeak.speech.backends import natural as natural_backend
from selectspeak.speech.backends.natural import (
    NaturalVoice,
    NaturalVoiceEngine,
    NaturalVoiceSpeaker,
    find_pinned_natural_voices,
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


def test_find_pinned_natural_voices_reads_extracted_packages(
    tmp_path: Path,
) -> None:
    package = (
        tmp_path
        / "versioned-packages"
        / "MicrosoftWindows.Voice.en-US.Aria.2_1.0.1.0_x64"
    )
    package.mkdir(parents=True)
    (package / "Tokens.xml").write_text(
        """<?xml version="1.0"?>
<Tokens><Category><Token name="Aria">
<String name="" value="Microsoft Aria (Natural) - English (United States)" />
</Token></Category></Tokens>
""",
        encoding="utf-8",
    )
    ignored = tmp_path / "not-a-voice"
    ignored.mkdir()

    voices = find_pinned_natural_voices(tmp_path)

    assert len(voices) == 1
    assert voices[0].package_path == str(package.resolve())
    assert voices[0].name == ("Microsoft Aria (Natural) - English (United States)")
    assert voices[0].source == "pinned"


def test_engine_falls_back_to_pinned_voice_when_no_installed_voice_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[str, tuple[Any, ...]]] = []

    class FakeFunction:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, *args: Any) -> int | None:
            events.append((self.name, args))
            if self.name == "ss_voice_initialize":
                return 0
            if self.name == "ss_voice_shutdown":
                return None
            return 0

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

    pinned = NaturalVoice(
        str(tmp_path / "Aria-1.0.1"),
        "Microsoft Aria",
        "en-US",
        "Aria",
        "pinned",
    )
    fake_dll = FakeDll()
    monkeypatch.setattr(
        natural_backend,
        "get_native_bridge",
        lambda _configured: SimpleNamespace(library=fake_dll),
    )
    monkeypatch.setattr(natural_backend, "find_pinned_natural_voices", lambda: [pinned])
    engine = NaturalVoiceEngine(AppConfig().speech, lambda _data: None, lambda *_: None)
    engine.close()

    assert engine.voice == pinned
    assert [name for name, _args in events if name == "ss_voice_initialize"] == [
        "ss_voice_initialize"
    ]
    assert [name for name, _args in events if name == "ss_voice_list"] == [
        "ss_voice_list"
    ]


def test_engine_prefers_matching_installed_voice_over_pinned_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    initialized_paths: list[str] = []

    class FakeFunction:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, *args: Any) -> int | None:
            if self.name == "ss_voice_list":
                callback = args[0]
                callback(
                    "C:/WindowsApps/AvaHD",
                    b"Microsoft Ava (Natural HD)",
                    b"en-US",
                    b"Ava",
                    None,
                )
                return 1
            if self.name == "ss_voice_initialize":
                initialized_paths.append(args[0])
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

    pinned = NaturalVoice(
        str(tmp_path / "Aria-1.0.1"),
        "Microsoft Aria (Natural)",
        "en-US",
        "Aria",
        "pinned",
    )
    fake_dll = FakeDll()
    monkeypatch.setattr(
        natural_backend,
        "get_native_bridge",
        lambda _configured: SimpleNamespace(library=fake_dll),
    )
    monkeypatch.setattr(natural_backend, "find_pinned_natural_voices", lambda: [pinned])
    config = AppConfig(preferred_voice_match="Ava").speech
    engine = NaturalVoiceEngine(config, lambda _data: None, lambda *_: None)

    assert engine.voice.name == "Microsoft Ava (Natural HD)"
    assert initialized_paths == ["C:/WindowsApps/AvaHD"]
    assert engine.available_voices == (
        NaturalVoice(
            "C:/WindowsApps/AvaHD",
            "Microsoft Ava (Natural HD)",
            "en-US",
            "Ava",
        ),
        pinned,
    )

    assert engine.select_voice(pinned.package_path) == pinned
    assert engine.voice == pinned
    assert initialized_paths == ["C:/WindowsApps/AvaHD", pinned.package_path]
    engine.close()


def test_select_voice_refreshes_packages_installed_after_engine_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = [
        NaturalVoice("C:/WindowsApps/AvaHD", "Microsoft Ava", "en-US", "Ava")
    ]
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

    def initialize(package_path: str, _credential: Any) -> int:
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
    monkeypatch.setattr(natural_backend, "find_pinned_natural_voices", list)
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
    speaker._word_callback = None
    speaker._playback = PlaybackController()
    request, _active = speaker._playback.submit(text)
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
    assert [value for event, value in player.events if event == "silence"] == [
        pytest.approx(0.1)
    ]
    boundary_positions = [
        value[1] for event, value in player.events if event == "boundary"
    ]
    assert boundary_positions == sorted(boundary_positions)
