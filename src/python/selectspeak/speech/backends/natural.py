from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...config import SpeechConfig
from ...native import (
    NativeNaturalSynthesisResult,
    VoiceAudioCallback,
    VoiceListCallback,
    VoiceWordCallback,
    check_native_status,
    get_native_bridge,
)
from ..contracts import SpeechEventCallback, TerminalStatus
from ..debug import SpeechDebugCallback, emit_speech_debug
from ..natural_identity import parse_natural_voice_key
from ..pcm import (
    PcmEvent,
    PcmFormat,
    PcmPlaybackSession,
    PcmPlayedWord,
    PcmTerminal,
    utf16_code_unit_offset,
)
from ..pipeline import AdaptiveSpeechSession, GenerationStatistics
from ..playback import PlaybackController, SpeechRequest

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


def _same_voice(left: NaturalVoice, right: NaturalVoice) -> bool:
    return (
        left.package_path.casefold() == right.package_path.casefold()
        and left.name.casefold() == right.name.casefold()
    )


@dataclass(frozen=True, slots=True)
class NaturalSynthesisResult:
    generated_frames: int
    synthesis_seconds: float
    buffered_frames_after_submit: int


def _decode(value: bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if value else ""


def discover_natural_voices(config: SpeechConfig) -> list[NaturalVoice]:
    """List selectable Natural Voices installed through Windows."""
    dll = get_native_bridge(config.native_dll).library
    voices: list[NaturalVoice] = []

    @VoiceListCallback
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

    dll.ss_voice_list(collect_voice, None)
    return voices


class NaturalVoiceEngine:
    """Thin ctypes owner for the process-wide native Natural Voice engine."""

    def __init__(
        self,
        config: SpeechConfig,
        audio_callback: AudioCallback | None = None,
        boundary_callback: BoundaryCallback | None = None,
    ) -> None:
        self._bridge = get_native_bridge(config.native_dll)
        self._dll = self._bridge.library
        self._audio_callback = VoiceAudioCallback(self._on_audio) if audio_callback else VoiceAudioCallback()
        self._word_callback = VoiceWordCallback(self._on_word) if boundary_callback else VoiceWordCallback()
        self._voice_callback = VoiceListCallback(self._on_voice)
        self._audio_consumer = audio_callback
        self._boundary_consumer = boundary_callback
        self._voices: list[NaturalVoice] = []

        self._dll.ss_voice_set_audio_callback(self._audio_callback, None)
        self._dll.ss_voice_set_word_callback(self._word_callback, None)
        check_native_status(
            self._dll.ss_voice_set_volume(config.speech_volume),
            "set Natural Voice volume",
        )
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
        if active_voice is not None and not any(_same_voice(voice, active_voice) for voice in voices):
            voices.append(active_voice)
        self._available_voices = tuple(voices)
        return self._available_voices

    def select_voice(self, package_path: str, sdk_voice_name: str) -> NaturalVoice:
        self.refresh_voices()
        selected = next(
            (
                voice
                for voice in self._available_voices
                if voice.package_path.casefold() == package_path.casefold()
                and voice.name.casefold() == sdk_voice_name.casefold()
            ),
            None,
        )
        if selected is None:
            raise NaturalVoiceError(
                f"Natural Voice is no longer available: {package_path} / {sdk_voice_name}"
            )
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

    def synthesize_to_audio(
        self,
        audio_session: PcmPlaybackSession,
        request_id: int,
        text: str,
        text_base_offset_utf16: int,
    ) -> NaturalSynthesisResult:
        native_result = NativeNaturalSynthesisResult(ctypes.sizeof(NativeNaturalSynthesisResult), 0, 0, 0, 0)
        status = self._dll.ss_voice_synthesize_to_audio(
            audio_session.native_handle_for_request(request_id),
            request_id,
            text,
            text_base_offset_utf16,
            ctypes.byref(native_result),
        )
        if status:
            check_native_status(status, "synthesize Natural Voice audio", self._last_error())
        if native_result.status != status:
            raise NaturalVoiceError("Natural Voice returned inconsistent synthesis status")
        return NaturalSynthesisResult(
            native_result.generated_frames,
            native_result.synthesis_duration_us / 1_000_000,
            native_result.buffered_frames_after_submit,
        )

    def stop(self) -> None:
        if self._dll.ss_voice_stop():
            raise NaturalVoiceError(self._last_error())

    def close(self) -> None:
        self._dll.ss_voice_shutdown()

    def _on_audio(
        self,
        data: Any,
        length: int,
        _context: int,
    ) -> None:
        if self._audio_consumer is not None:
            self._audio_consumer(ctypes.string_at(data, length))

    def _on_word(self, audio_offset: int, text_offset: int, length: int, _context: int) -> None:
        if self._boundary_consumer is not None:
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
        exact_identity = parse_natural_voice_key(preferred)
        if exact_identity is not None:
            package_path, sdk_voice_name = exact_identity
            exact_matches = [
                voice
                for voice in voices
                if voice.package_path.casefold() == package_path.casefold()
                and voice.name.casefold() == sdk_voice_name.casefold()
            ]
            if exact_matches:
                selected = exact_matches[0]
                return [selected, *(voice for voice in voices if voice is not selected)]

        legacy_package_matches = [
            voice for voice in voices if voice.package_path.casefold() == preferred.casefold()
        ]
        if legacy_package_matches:
            # Package-only settings cannot distinguish SDK voices. The first
            # case-insensitive SDK name is a stable, documented fallback.
            selected = min(
                legacy_package_matches,
                key=lambda voice: (voice.name.casefold(), voice.display_name.casefold()),
            )
            return [selected, *(voice for voice in voices if voice is not selected)]

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

    def synthesize_to_audio(
        self,
        audio_session: PcmPlaybackSession,
        request_id: int,
        text: str,
        text_base_offset_utf16: int,
    ) -> NaturalSynthesisResult: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
    def refresh_voices(self) -> tuple[NaturalVoice, ...]: ...
    def select_voice(self, package_path: str, sdk_voice_name: str) -> NaturalVoice: ...


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
        self._generation_statistics = GenerationStatistics()
        self._session_lock = threading.Lock()
        self._audio_session: PcmPlaybackSession | None = None
        self._terminal_event: threading.Event | None = None
        self._terminal_status = TerminalStatus.NONE
        self._close_lock = threading.Lock()
        self._closed = False
        self._engine: _Engine = NaturalVoiceEngine(config)
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

    def select_voice(self, package_path: str, sdk_voice_name: str) -> NaturalVoice:
        self.stop()
        selected = self._engine.select_voice(package_path, sdk_voice_name)
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
            self._stop_active(TerminalStatus.SUPERSEDED)
        return True

    def stop(self) -> None:
        _generation, active = self._playback.cancel()
        if active:
            self._stop_active(TerminalStatus.CANCELLED)

    def pause(self) -> None:
        if self._playback.pause_now():
            audio_session = self._current_audio_session()
            if audio_session is not None:
                audio_session.pause()

    def resume(self) -> None:
        if self._playback.resume_now():
            audio_session = self._current_audio_session()
            if audio_session is not None:
                audio_session.resume()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        active = self._playback.close()
        if active:
            try:
                self._stop_active(TerminalStatus.CLOSED)
            except Exception:
                logger.exception("natural_voice.close_stop_failed")
        try:
            self._thread.join()
        finally:
            self._engine.close()
        logger.info("natural_voice.closed")

    def _stop_active(self, reason: TerminalStatus) -> None:
        audio_session = self._current_audio_session()
        if audio_session is not None:
            try:
                audio_session.stop(reason)
            except RuntimeError:
                pass
        try:
            self._engine.stop()
        except NaturalVoiceError:
            if self._playback.active:
                raise

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
        if not self._playback.is_current(request.generation):
            return
        self._synthesize_request(request)

    def _synthesize_request(self, request: _SpeechRequest) -> None:
        session = AdaptiveSpeechSession.start(request.text, "natural", self._generation_statistics)
        if session is None:
            self._playback.complete(request.generation)
            return
        terminal_event = threading.Event()
        audio_session = PcmPlaybackSession(
            request.request_id,
            request.text,
            PcmFormat(SAMPLE_RATE),
            lambda event: self._on_audio_event(request.generation, event),
            dll_path=self._config.native_dll,
        )
        with self._session_lock:
            self._audio_session = audio_session
            self._terminal_event = terminal_event
            self._terminal_status = TerminalStatus.NONE
        try:
            if not self._playback.is_current(request.generation):
                audio_session.stop(TerminalStatus.CANCELLED)
            elif self._playback.paused:
                audio_session.pause()
            self._synthesize_chunks(request, session, audio_session)
            if self._playback.is_current(request.generation):
                audio_session.finish_input()
            terminal_event.wait()
        finally:
            audio_session.close()
            with self._session_lock:
                if self._audio_session is audio_session:
                    self._audio_session = None
                    self._terminal_event = None

    def _synthesize_chunks(
        self,
        request: _SpeechRequest,
        session: AdaptiveSpeechSession,
        audio_session: PcmPlaybackSession,
    ) -> None:
        buffered_frames = 0
        submitted_frames = 0
        while self._playback.is_current(request.generation):
            generated_frames, buffered_frames = self._synthesize_chunk(
                request, session, audio_session, submitted_frames
            )
            submitted_frames += generated_frames
            if not session.remaining_characters:
                return
            if session.decision.segment.pause_after:
                silence_frames = round(self._config.structure_pause_seconds * SAMPLE_RATE)
                if silence_frames:
                    result = audio_session.submit_bounded(b"\0\0" * silence_frames)
                    buffered_frames = result.buffered_frames_after_submit
                    submitted_frames += result.accepted_frames
            if not session.advance(buffered_frames / SAMPLE_RATE):
                return

    def _synthesize_chunk(
        self,
        request: _SpeechRequest,
        session: AdaptiveSpeechSession,
        audio_session: PcmPlaybackSession,
        submitted_frames: int,
    ) -> tuple[int, int]:
        segment = session.decision.segment
        result = self._engine.synthesize_to_audio(
            audio_session,
            request.request_id,
            segment.text,
            utf16_code_unit_offset(request.text, segment.offset),
        )
        session.record_generation(result.synthesis_seconds)
        emit_speech_debug(
            session.debug_event(
                result.synthesis_seconds,
                result.generated_frames / SAMPLE_RATE,
            ),
            getattr(self, "_debug_callback", None),
            None,
            byte_offset=submitted_frames * 2,
        )
        return result.generated_frames, result.buffered_frames_after_submit

    def _on_audio_event(self, generation: int, event: PcmEvent) -> None:
        if isinstance(event, PcmPlayedWord):
            self._playback.played_word(generation, event.text_position, event.text_length)
            return
        if not isinstance(event, PcmTerminal):
            return
        if event.status is TerminalStatus.COMPLETED:
            self._playback.complete(generation)
        elif event.status is TerminalStatus.FAILED:
            self._playback.fail(generation)
        with self._session_lock:
            self._terminal_status = event.status
            terminal_event = self._terminal_event
        if terminal_event is not None:
            terminal_event.set()

    def _current_audio_session(self) -> PcmPlaybackSession | None:
        with self._session_lock:
            return self._audio_session

    def _is_superseded(self, generation: int) -> bool:
        return not self._playback.is_current(generation)
