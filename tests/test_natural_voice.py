from pathlib import Path

import pytest

from selectspeak.natural_voice import (
    NaturalVoice,
    NaturalVoiceEngine,
    NaturalVoiceError,
    find_natural_voice_dll,
)


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
