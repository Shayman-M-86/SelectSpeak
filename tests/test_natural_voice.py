import threading
from pathlib import Path
from typing import Any

import pytest

from selectspeak.config import AppConfig
from selectspeak.natural_voice import (
    NaturalVoice,
    NaturalVoiceEngine,
    NaturalVoiceError,
    NaturalVoiceSpeaker,
    _SpeechRequest,
    find_natural_voice_dll,
)
from selectspeak.speech_pipeline import GenerationStatistics


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
    speaker._config = AppConfig(structure_pause_seconds=0.1)
    speaker._word_callback = None
    speaker._condition = threading.Condition()
    speaker._generation = 1
    speaker._active_generation = None
    speaker._completed_generation = 0
    speaker._paused = False
    speaker._request_text = ""
    speaker._segment_text_offset = 0
    speaker._segment_audio_base = 0
    speaker._generation_statistics = GenerationStatistics()
    player = _FakePlayer()
    speaker._player = player
    engine = _FakeEngine(speaker)
    speaker._engine = engine

    speaker._speak_request(_SpeechRequest(1, text))

    assert len(engine.spoken) > 2
    assert [event for event, _ in player.events].count("start") == 1
    assert [event for event, _ in player.events].count("finish") == 1
    assert [value for event, value in player.events if event == "silence"] == [
        pytest.approx(0.1)
    ]
    boundary_positions = [
        value[1] for event, value in player.events if event == "boundary"
    ]
    assert boundary_positions == sorted(boundary_positions)
