from pathlib import Path
from typing import Any

import pytest

from selectspeak.config import AppConfig
from selectspeak.speech.backends import natural as natural_backend
from selectspeak.speech.backends.natural import (
    NaturalVoice,
    NaturalVoiceEngine,
    NaturalVoiceError,
    NaturalVoiceSpeaker,
    find_natural_voice_dll,
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
    assert voices[0].name == (
        "Microsoft Aria (Natural) - English (United States)"
    )
    assert voices[0].source == "pinned"


def test_engine_uses_pinned_voice_without_opening_installed_packages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[str, tuple[Any, ...]]] = []

    class FakeFunction:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, *args: Any) -> int | None:
            events.append((self.name, args))
            if self.name == "nv_initialize":
                return 0
            if self.name == "nv_shutdown":
                return None
            return 0

    class FakeDll:
        def __init__(self) -> None:
            for name in (
                "nv_list_voices",
                "nv_initialize",
                "nv_set_audio_callback",
                "nv_set_word_callback",
                "nv_speak",
                "nv_stop",
                "nv_shutdown",
                "nv_last_error",
            ):
                setattr(self, name, FakeFunction(name))

    class FakeDirectory:
        def close(self) -> None:
            pass

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
        "find_natural_voice_dll",
        lambda _configured: tmp_path / "bridge.dll",
    )
    monkeypatch.setattr(
        natural_backend, "find_pinned_natural_voices", lambda: [pinned]
    )
    monkeypatch.setattr(natural_backend.ctypes, "CDLL", lambda _path: fake_dll)
    monkeypatch.setattr(
        natural_backend.os,
        "add_dll_directory",
        lambda _path: FakeDirectory(),
        raising=False,
    )

    engine = NaturalVoiceEngine(AppConfig().speech, lambda _data: None, lambda *_: None)
    engine.close()

    assert engine.voice == pinned
    assert [name for name, _args in events if name == "nv_initialize"] == [
        "nv_initialize"
    ]
    assert not any(name == "nv_list_voices" for name, _args in events)


def test_find_natural_voice_dll_accepts_an_explicit_path(tmp_path: Path) -> None:
    dll = tmp_path / "bridge.dll"
    dll.touch()

    assert find_natural_voice_dll(str(dll)) == dll.resolve()


def test_find_natural_voice_dll_reports_build_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SELECTSPEAK_NATURAL_VOICE_DLL", raising=False)
    monkeypatch.setattr(Path, "is_file", lambda _path: False)

    with pytest.raises(NaturalVoiceError, match="build native/natural_voice"):
        find_natural_voice_dll("Z:/not-present/selectspeak_natural_voice.dll")


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
