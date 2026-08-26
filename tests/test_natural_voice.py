import ctypes
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from selectspeak.config import AppConfig
from selectspeak.speech.backends import natural as natural_backend
from selectspeak.speech.backends.natural import (
    NaturalSynthesisResult,
    NaturalVoice,
    NaturalVoiceEngine,
    NaturalVoiceError,
    NaturalVoiceSpeaker,
)
from selectspeak.speech.contracts import TerminalStatus
from selectspeak.speech.pcm import PcmPlayedWord, PcmSubmitResult, PcmTerminal
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
                "ss_voice_set_volume",
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
    assert initialized_arguments == [(installed[1].package_path, installed[1].name.encode("utf-8"))]
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
        ss_voice_set_volume = FakeFunction()
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
        ss_voice_set_volume = FakeFunction(lambda *_args: 0)
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


def test_engine_synthesis_passes_the_native_request_handle_and_telemetry() -> None:
    calls: list[tuple[Any, ...]] = []

    class Dll:
        def ss_voice_synthesize_to_audio(self, *args: Any) -> int:
            calls.append(args[:-1])
            result = args[-1]._obj
            result.status = 0
            result.generated_frames = 12_000
            result.synthesis_duration_us = 250_000
            result.buffered_frames_after_submit = 36_000
            return 0

        def ss_voice_last_error(self, *_args: Any) -> int:
            return 1

    class Session:
        def native_handle_for_request(self, request_id: int) -> ctypes.c_uint64:
            assert request_id == 41
            return ctypes.c_uint64(9)

    engine = object.__new__(NaturalVoiceEngine)
    engine._dll = Dll()

    result = engine.synthesize_to_audio(Session(), 41, "hello", 7)

    assert len(calls) == 1
    assert calls[0][0].value == 9
    assert calls[0][1:] == (41, "hello", 7)
    assert result == NaturalSynthesisResult(12_000, 0.25, 36_000)


class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, int]] = []

    def synthesize_to_audio(
        self,
        _audio_session: Any,
        request_id: int,
        text: str,
        text_base_offset_utf16: int,
    ) -> NaturalSynthesisResult:
        self.calls.append((request_id, text, text_base_offset_utf16))
        return NaturalSynthesisResult(len(text) * 100, 0.01, 24_000)


def test_natural_voice_synthesizes_directly_into_one_native_audio_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    speaker._generation_statistics = GenerationStatistics()
    speaker._session_lock = threading.Lock()
    speaker._audio_session = None
    speaker._terminal_event = None
    speaker._terminal_status = TerminalStatus.NONE
    speaker._debug_callback = None
    sessions: list[Any] = []

    class FakeAudioSession:
        def __init__(self, request_id: int, request_text: str, *_args: Any, **_kwargs: Any) -> None:
            self.request_id = request_id
            self.request_text = request_text
            self.callback = _args[1]
            self.silence_frames = 0
            self.finished = False
            self.closed = False
            sessions.append(self)

        def submit_bounded(self, pcm: bytes) -> PcmSubmitResult:
            self.silence_frames += len(pcm) // 2
            return PcmSubmitResult(len(pcm) // 2, 24_000)

        def finish_input(self) -> None:
            self.finished = True
            self.callback(PcmPlayedWord(self.request_id, 0, 1))
            self.callback(PcmTerminal(self.request_id, TerminalStatus.COMPLETED, 0))

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(natural_backend, "PcmPlaybackSession", FakeAudioSession)
    engine = _FakeEngine()
    speaker._engine = engine

    speaker._speak_request(request)

    assert len(engine.calls) == 2
    assert [call[0] for call in engine.calls] == [1, 1]
    assert engine.calls[0][2] == 0
    assert engine.calls[1][2] > 0
    assert len(sessions) == 1
    assert sessions[0].silence_frames == 2_400
    assert sessions[0].finished and sessions[0].closed


def test_natural_voice_close_cancels_joins_and_releases_engine() -> None:
    events: list[str] = []

    class AudioSession:
        def stop(self, reason: TerminalStatus) -> None:
            events.append(f"audio.stop.{reason.name.lower()}")

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
    speaker._session_lock = threading.Lock()
    speaker._audio_session = AudioSession()
    speaker._terminal_event = threading.Event()
    speaker._terminal_status = TerminalStatus.NONE
    speaker._playback = PlaybackController()
    request, _active = speaker._playback.submit(1, "Read this", lambda _event: None)
    assert speaker._playback.next_request() == request
    speaker._engine = Engine()
    speaker._thread = Worker()

    speaker.close()
    speaker.close()

    assert events == [
        "audio.stop.closed",
        "engine.stop",
        "worker.join",
        "engine.close",
    ]
