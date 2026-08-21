from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...config import SpeechConfig
from ...native import get_native_bridge
from ..contracts import SpeechEventCallback
from ..debug import SpeechDebugCallback, emit_speech_debug
from ..pipeline import AdaptiveSpeechSession, GenerationStatistics
from ..playback import PlaybackController, SpeechRequest
from ..waveout import WaveOutPlayer

SAMPLE_RATE = 24_000

logger = logging.getLogger(__name__)

AudioCallback = Callable[[bytes], None]
BoundaryCallback = Callable[[int, int, int], None]


class NaturalVoiceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NaturalVoice:
    package_path: str
    name: str
    locale: str
    display_name: str


_AUDIO_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32, ctypes.c_void_p)
_WORD_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_uint64,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_void_p,
)
_VOICE_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_wchar_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
)


def _decode(value: bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if value else ""


def discover_natural_voices(config: SpeechConfig) -> list[NaturalVoice]:
    """List selectable Natural Voices installed through Windows."""
    dll = get_native_bridge(config.native_dll).library
    voices: list[NaturalVoice] = []

    @_VOICE_CALLBACK
    def collect_voice(
        package_path: str,
        name: bytes,
        locale: bytes,
        display_name: bytes,
        _context: int,
    ) -> None:
        voices.append(
            NaturalVoice(
                package_path,
                _decode(name),
                _decode(locale),
                _decode(display_name),
            )
        )

    dll.ss_voice_list.argtypes = [_VOICE_CALLBACK, ctypes.c_void_p]
    dll.ss_voice_list.restype = ctypes.c_uint32
    dll.ss_voice_list(collect_voice, None)
    return voices


class NaturalVoiceEngine:
    """Thin ctypes owner for the process-wide native Natural Voice engine."""

    def __init__(
        self,
        config: SpeechConfig,
        audio_callback: AudioCallback,
        boundary_callback: BoundaryCallback,
    ) -> None:
        self._bridge = get_native_bridge(config.native_dll)
        self._dll = self._bridge.library
        self._configure_api()
        self._audio_callback = _AUDIO_CALLBACK(self._on_audio)
        self._word_callback = _WORD_CALLBACK(self._on_word)
        self._voice_callback = _VOICE_CALLBACK(self._on_voice)
        self._audio_consumer = audio_callback
        self._boundary_consumer = boundary_callback
        self._voices: list[NaturalVoice] = []

        self._dll.ss_voice_set_audio_callback(self._audio_callback, None)
        self._dll.ss_voice_set_word_callback(self._word_callback, None)
        failures: list[str] = []
        installed = self._enumerate_installed_voices()
        candidates = self._ordered_voices(installed, config.preferred_voice_match)
        self._available_voices = tuple(candidates)
        if self._initialize_first(candidates, failures):
            return
        if not installed:
            raise NaturalVoiceError(self._last_error() or "No Windows Natural Voices are installed")
        raise NaturalVoiceError(
            "No installed Natural Voice could be initialized with the installed "
            "Windows speech runtime configuration. " + " | ".join(failures)
        )

    @property
    def available_voices(self) -> tuple[NaturalVoice, ...]:
        return self._available_voices

    def refresh_voices(self) -> tuple[NaturalVoice, ...]:
        """Refresh voices installed through Windows without recreating the engine."""
        voices = self._enumerate_installed_voices()
        active_voice = getattr(self, "voice", None)
        if active_voice is not None and not any(
            voice.package_path.casefold() == active_voice.package_path.casefold() for voice in voices
        ):
            voices.append(active_voice)
        self._available_voices = tuple(voices)
        return self._available_voices

    def select_voice(self, package_path: str) -> NaturalVoice:
        self.refresh_voices()
        selected = next(
            (
                voice
                for voice in self._available_voices
                if voice.package_path.casefold() == package_path.casefold()
            ),
            None,
        )
        if selected is None:
            raise NaturalVoiceError(f"Natural Voice is no longer available: {package_path}")
        previous = self.voice
        failures: list[str] = []
        if self._initialize_first([selected], failures):
            return selected

        rollback_failures: list[str] = []
        self._initialize_first([previous], rollback_failures)
        raise NaturalVoiceError(
            "The selected Natural Voice could not be initialized. " + " | ".join(failures)
        )

    def _enumerate_installed_voices(self) -> list[NaturalVoice]:
        self._voices.clear()
        self._dll.ss_voice_list(self._voice_callback, None)
        return list(self._voices)

    def _initialize_first(
        self,
        candidates: list[NaturalVoice],
        failures: list[str],
    ) -> bool:
        for candidate in candidates:
            logger.info(
                "natural_voice.probing voice=%s locale=%s package_path=%s",
                candidate.name,
                candidate.locale,
                candidate.package_path,
            )
            if not self._dll.ss_voice_initialize(
                candidate.package_path,
                candidate.name.encode("utf-8"),
            ):
                self.voice = candidate
                logger.info(
                    "natural_voice.selected voice=%s locale=%s package_path=%s available_voice_count=%s",
                    candidate.name,
                    candidate.locale,
                    candidate.package_path,
                    len(candidates),
                )
                return True
            failures.append(f"{candidate.name}: {self._last_error()}")
        return False

    def speak(self, text: str) -> None:
        if self._dll.ss_voice_speak(text):
            raise NaturalVoiceError(self._last_error())

    def stop(self) -> None:
        if self._dll.ss_voice_stop():
            raise NaturalVoiceError(self._last_error())

    def close(self) -> None:
        self._dll.ss_voice_shutdown()

    def _configure_api(self) -> None:
        self._dll.ss_voice_list.argtypes = [_VOICE_CALLBACK, ctypes.c_void_p]
        self._dll.ss_voice_list.restype = ctypes.c_uint32
        self._dll.ss_voice_initialize.argtypes = [ctypes.c_wchar_p, ctypes.c_char_p]
        self._dll.ss_voice_initialize.restype = ctypes.c_int
        self._dll.ss_voice_set_audio_callback.argtypes = [
            _AUDIO_CALLBACK,
            ctypes.c_void_p,
        ]
        self._dll.ss_voice_set_word_callback.argtypes = [
            _WORD_CALLBACK,
            ctypes.c_void_p,
        ]
        self._dll.ss_voice_speak.argtypes = [ctypes.c_wchar_p]
        self._dll.ss_voice_speak.restype = ctypes.c_int
        self._dll.ss_voice_stop.restype = ctypes.c_int
        self._dll.ss_voice_shutdown.restype = None
        self._dll.ss_voice_last_error.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        self._dll.ss_voice_last_error.restype = ctypes.c_uint32

    def _on_audio(
        self,
        data: Any,
        length: int,
        _context: int,
    ) -> None:
        self._audio_consumer(ctypes.string_at(data, length))

    def _on_word(self, audio_offset: int, text_offset: int, length: int, _context: int) -> None:
        self._boundary_consumer(audio_offset, text_offset, length)

    def _on_voice(
        self,
        package_path: str,
        name: bytes,
        locale: bytes,
        display_name: bytes,
        _context: int,
    ) -> None:
        self._voices.append(NaturalVoice(package_path, _decode(name), _decode(locale), _decode(display_name)))

    def _last_error(self) -> str:
        required = self._dll.ss_voice_last_error(None, 0)
        buffer = ctypes.create_string_buffer(max(required, 1))
        self._dll.ss_voice_last_error(buffer, len(buffer))
        return buffer.value.decode("utf-8", errors="replace")

    @staticmethod
    def _choose_voice(voices: list[NaturalVoice], preferred: str) -> NaturalVoice:
        return NaturalVoiceEngine._ordered_voices(voices, preferred)[0]

    @staticmethod
    def _ordered_voices(voices: list[NaturalVoice], preferred: str) -> list[NaturalVoice]:
        needle = preferred.casefold().strip()
        if not needle:
            return list(voices)

        def matches(voice: NaturalVoice) -> bool:
            haystack = " ".join((voice.name, voice.display_name, voice.locale, voice.package_path)).casefold()
            return needle in haystack

        return [voice for voice in voices if matches(voice)] + [
            voice for voice in voices if not matches(voice)
        ]


_SpeechRequest = SpeechRequest


class _Engine(Protocol):
    @property
    def voice(self) -> NaturalVoice: ...

    @property
    def available_voices(self) -> tuple[NaturalVoice, ...]: ...

    def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
    def refresh_voices(self) -> tuple[NaturalVoice, ...]: ...
    def select_voice(self, package_path: str) -> NaturalVoice: ...


class NaturalVoiceSpeaker:
    """Match the app's speaker contract using the direct local speech engine."""

    def __init__(
        self,
        config: SpeechConfig,
        debug_callback: SpeechDebugCallback | None = None,
    ) -> None:
        self._config = config
        self._debug_callback = debug_callback
        self._playback = PlaybackController()
        self._request_generation = 0
        self._segment_text_offset = 0
        self._segment_audio_base = 0
        self._generation_statistics = GenerationStatistics()
        self._close_lock = threading.Lock()
        self._closed = False
        self._player = WaveOutPlayer(
            self._on_played_word,
            config.speech_volume,
            debug_callback=debug_callback,
        )
        self._engine: _Engine = NaturalVoiceEngine(config, self._on_engine_audio, self._on_engine_boundary)
        self._thread = threading.Thread(target=self._run, name="NaturalVoiceSpeaker")
        self._thread.start()

    @property
    def active(self) -> bool:
        return self._playback.active

    @property
    def paused(self) -> bool:
        return self._playback.paused

    @property
    def voice(self) -> NaturalVoice:
        return self._engine.voice

    @property
    def available_voices(self) -> tuple[NaturalVoice, ...]:
        return self._engine.available_voices

    def refresh_voices(self) -> tuple[NaturalVoice, ...]:
        return self._engine.refresh_voices()

    def select_voice(self, package_path: str) -> NaturalVoice:
        self.stop()
        selected = self._engine.select_voice(package_path)
        logger.info(
            "natural_voice.changed voice=%s package_path=%s",
            selected.name,
            selected.package_path,
        )
        return selected

    def speak(self, request_id: int, text: str, callback: SpeechEventCallback) -> bool:
        if len(text) < self._config.minimum_text_length:
            return False
        try:
            request, active = self._playback.submit(request_id, text, callback)
        except RuntimeError as error:
            raise NaturalVoiceError("The Natural Voice worker has failed") from error
        if active:
            self._player.stop()
            self._engine.stop()
        return True

    def stop(self) -> None:
        _generation, active = self._playback.cancel()
        if active:
            self._stop_active()

    def pause(self) -> None:
        if self._playback.pause_now():
            self._player.pause()

    def resume(self) -> None:
        if self._playback.resume_now():
            self._player.resume()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        active = self._playback.close()
        if active:
            try:
                self._stop_active()
            except Exception:
                logger.exception("natural_voice.close_stop_failed")
        try:
            self._thread.join()
        finally:
            self._engine.close()
        logger.info("natural_voice.closed")

    def _stop_active(self) -> None:
        # Silence first, then cancel the synthesizer before waiting for WaveOut
        # cleanup. This avoids both audible delay and the former one-second wait.
        self._player.request_stop()
        try:
            self._engine.stop()
        finally:
            self._player.wait_until_stopped()

    def _run(self) -> None:
        while True:
            request = self._playback.next_request()
            if request is None:
                logger.debug("natural_voice.worker.closed")
                return
            if not self._playback.is_current(request.generation):
                continue
            try:
                self._speak_request(request)
            except Exception:
                if self._is_superseded(request.generation):
                    continue
                logger.exception("natural_voice.request.failed generation=%s", request.generation)
                self._playback.fail(request.generation)
                return

    def _speak_request(self, request: _SpeechRequest) -> None:
        if not self._playback.begin(request.generation):
            return
        self._synthesize_request(request)
        self._playback.complete(request.generation)

    def _synthesize_request(self, request: _SpeechRequest) -> None:
        session = AdaptiveSpeechSession.start(request.text, "natural", self._generation_statistics)
        if session is None:
            return
        self._request_generation = request.generation
        self._player.start()
        try:
            self._synthesize_chunks(request.generation, session)
        finally:
            self._player.finish()

    def _synthesize_chunks(self, generation: int, session: AdaptiveSpeechSession) -> None:
        while self._playback.is_current(generation):
            self._synthesize_chunk(session)
            if not session.remaining_characters:
                return
            session.queue_structure_pause(self._player.feed_silence, self._config.structure_pause_seconds)
            if not session.advance(self._player.buffered_seconds):
                return

    def _synthesize_chunk(self, session: AdaptiveSpeechSession) -> None:
        segment = session.decision.segment
        self._segment_text_offset = segment.offset
        self._segment_audio_base = self._player.fed_bytes
        started_at = time.monotonic()
        self._engine.speak(segment.text)
        synthesis_seconds = time.monotonic() - started_at
        generated_bytes = self._player.fed_bytes - self._segment_audio_base
        session.record_generation(synthesis_seconds)
        emit_speech_debug(
            session.debug_event(synthesis_seconds, generated_bytes / (SAMPLE_RATE * 2)),
            getattr(self, "_debug_callback", None),
            getattr(self._player, "add_debug_marker", None),
            byte_offset=self._segment_audio_base,
        )

    def _on_engine_audio(self, data: bytes) -> None:
        self._player.feed(data)

    def _on_engine_boundary(self, audio_offset: int, text_offset: int, length: int) -> None:
        self._player.add_boundary(
            audio_offset,
            self._segment_text_offset + text_offset,
            length,
            base_byte_offset=self._segment_audio_base,
        )

    def _on_played_word(self, position: int, length: int) -> None:
        self._playback.played_word(self._request_generation, position, length)

    def _is_superseded(self, generation: int) -> bool:
        return not self._playback.is_current(generation)
