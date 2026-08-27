from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass

import numpy as np
from supertonic import TTS

from ...config import SpeechConfig
from ...config.paths import model_dir
from ..contracts import SpeechEventCallback, TerminalStatus
from ..debug import SpeechDebugCallback, emit_speech_debug
from ..pcm import (
    PcmEvent,
    PcmFormat,
    PcmPlaybackSession,
    PcmPlayedWord,
    PcmTerminal,
    pcm_boundary_from_codepoints,
)
from ..pipeline import AdaptiveSpeechSession, GenerationStatistics
from ..playback import PlaybackController, SpeechRequest
from ..segments import SpeechSegment

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44_100
_WORD_PATTERN = re.compile(r"[\w]+(?:[’'-][\w]+)*", re.UNICODE)
EDGE_PADDING_SECONDS = 0.015
LEADING_SCAN_SECONDS = 0.5
TRAILING_SCAN_SECONDS = 0.75


@dataclass(frozen=True, slots=True)
class EstimatedBoundary:
    seconds: float
    position: int
    length: int


_SpeechRequest = SpeechRequest


@dataclass(frozen=True, slots=True)
class _PreparedSegment:
    offset: int
    spoken: str
    pcm: bytes
    audio_seconds: float
    leading_silence_seconds: float
    spoken_seconds: float
    synthesis_ms: int
    pause_after: bool


def estimate_word_boundaries(text: str, duration: float) -> list[EstimatedBoundary]:
    """Estimate highlights from exact audio duration and weighted word lengths."""
    matches = list(_WORD_PATTERN.finditer(text))
    if not matches or duration <= 0:
        return []

    units: list[tuple[float, float]] = []
    for index, match in enumerate(matches):
        letters = sum(character.isalpha() for character in match.group())
        spoken_weight = max(1.0, letters**0.65)
        gap_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        punctuation = text[match.end() : gap_end]
        pause_weight = 0.0
        if any(mark in punctuation for mark in ".!?"):
            pause_weight = 0.8
        elif any(mark in punctuation for mark in ";:"):
            pause_weight = 0.5
        elif "," in punctuation:
            pause_weight = 0.3
        units.append((spoken_weight, pause_weight))

    total_units = sum(spoken + pause for spoken, pause in units)
    cursor = 0.0
    boundaries: list[EstimatedBoundary] = []
    for match, (spoken, pause) in zip(matches, units, strict=True):
        boundaries.append(
            EstimatedBoundary(
                seconds=duration * cursor / total_units,
                position=match.start(),
                length=match.end() - match.start(),
            )
        )
        cursor += spoken + pause
    return boundaries


def normalize_edge_silence(
    audio: np.ndarray,
    sample_rate: int,
    *,
    padding_seconds: float = EDGE_PADDING_SECONDS,
    leading_scan_seconds: float = LEADING_SCAN_SECONDS,
    trailing_scan_seconds: float = TRAILING_SCAN_SECONDS,
) -> tuple[np.ndarray, float, float]:
    """Trim generated edge silence using only small prefix and tail scans."""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not samples.size:
        return samples, 0.0, 0.0
    window_size = max(1, sample_rate // 100)
    if samples.size < window_size:
        return samples, 0.0, samples.size / sample_rate
    peak = float(np.max(np.abs(samples)))
    threshold = max(0.001, peak * 0.012)

    prefix_length = min(samples.size, round(leading_scan_seconds * sample_rate))
    prefix_length -= prefix_length % window_size
    tail_length = min(samples.size, round(trailing_scan_seconds * sample_rate))
    tail_length -= tail_length % window_size
    if not prefix_length or not tail_length:
        return samples, 0.0, samples.size / sample_rate

    prefix = samples[:prefix_length].reshape(-1, window_size)
    prefix_rms = np.sqrt(np.mean(prefix**2, axis=1))
    prefix_active = np.flatnonzero(prefix_rms > threshold)
    active_start = int(prefix_active[0]) * window_size if prefix_active.size else 0

    tail_start = samples.size - tail_length
    tail = samples[tail_start:].reshape(-1, window_size)
    tail_rms = np.sqrt(np.mean(tail**2, axis=1))
    tail_active = np.flatnonzero(tail_rms > threshold)
    active_end = (
        min(
            samples.size,
            tail_start + (int(tail_active[-1]) + 1) * window_size,
        )
        if tail_active.size
        else samples.size
    )

    padding = round(padding_seconds * sample_rate)
    play_from = max(0, active_start - padding)
    play_until = min(samples.size, active_end + padding)
    if play_until <= play_from:
        return samples, 0.0, samples.size / sample_rate
    normalized = samples[play_from:play_until]
    leading = (active_start - play_from) / sample_rate
    spoken_seconds = (active_end - active_start) / sample_rate
    return normalized, leading, spoken_seconds


class SupertonicSpeaker:
    """Run Supertonic locally and adapt its waveform to the app speaker contract."""

    def __init__(
        self,
        config: SpeechConfig,
        debug_callback: SpeechDebugCallback | None = None,
    ) -> None:
        self._config = config
        self._debug_callback = debug_callback
        self._playback = PlaybackController()
        # A cancelled inference cannot be interrupted by the Supertonic API.
        # Serialize it with the next request so two ONNX runs cannot contend
        # for the CPU and turn a cancellation into a large startup outlier.
        self._synthesis_lock = threading.Lock()
        self._request_generation = 0
        self._generation_statistics = GenerationStatistics()
        self._close_lock = threading.Lock()
        self._closed = False
        logger.info("supertonic.model.loading")
        self._tts = TTS(model_dir=model_dir("supertonic3"), auto_download=True)
        self._style = self._tts.get_voice_style(config.supertonic_voice)
        self._sample_rate = int(getattr(self._tts, "sample_rate", SAMPLE_RATE))
        self._session_lock = threading.Lock()
        self._audio_session: PcmPlaybackSession | None = None
        self._terminal_event: threading.Event | None = None
        self._thread = threading.Thread(target=self._run, name="SupertonicSpeaker")
        self._thread.start()
        logger.info(
            "supertonic.model.loaded voice=%s language=%s sample_rate=%s",
            config.supertonic_voice,
            config.supertonic_language,
            self._sample_rate,
        )

    def speak(self, request_id: int, text: str, callback: SpeechEventCallback) -> bool:
        if len(text) < self._config.minimum_text_length:
            return False
        request, active = self._playback.submit(request_id, text, callback)
        if active:
            self._stop_active(TerminalStatus.SUPERSEDED)
        return True

    def stop(self) -> None:
        _generation, active = self._playback.cancel()
        if active:
            self._stop_active(TerminalStatus.CANCELLED)

    def pause(self) -> None:
        if self._playback.pause_now():
            if session := self._current_audio_session():
                session.pause()

    def resume(self) -> None:
        if self._playback.resume_now():
            if session := self._current_audio_session():
                session.resume()

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
                logger.exception("supertonic.close_stop_failed")
        # Supertonic cannot cancel an ONNX inference. Joining here guarantees
        # that it has settled before application/native teardown continues.
        self._thread.join()
        logger.info("supertonic.closed")

    def _run(self) -> None:
        while True:
            request = self._playback.next_request()
            if request is None:
                logger.debug("supertonic.worker.closed")
                return
            if not self._playback.is_current(request.generation):
                continue
            try:
                self._speak_request(request)
            except Exception:
                if self._is_superseded(request.generation):
                    continue
                logger.exception("supertonic.request.failed generation=%s", request.generation)
                self._playback.fail(request.generation)
                return

    def _speak_request(self, request: _SpeechRequest) -> None:
        if not self._playback.is_current(request.generation):
            return
        self._synthesize_request(request)

    def _synthesize_request(self, request: _SpeechRequest) -> None:
        session = AdaptiveSpeechSession.start(request.text, "supertonic", self._generation_statistics)
        if session is None:
            return
        prepared = self._prepare_chunk(session)
        if self._is_superseded(request.generation):
            return
        self._request_generation = request.generation
        terminal_event = threading.Event()
        audio_session = PcmPlaybackSession(
            request.request_id,
            request.text,
            PcmFormat(self._sample_rate),
            lambda event: self._on_audio_event(request.generation, event),
            dll_path=self._config.native_dll,
        )
        with self._session_lock:
            self._audio_session = audio_session
            self._terminal_event = terminal_event
        try:
            if self._playback.paused:
                audio_session.pause()
            self._queue_chunks(request, session, prepared, audio_session)
            if self._playback.is_current(request.generation):
                audio_session.finish_input()
            terminal_event.wait()
        finally:
            audio_session.close()
            with self._session_lock:
                if self._audio_session is audio_session:
                    self._audio_session = None
                    self._terminal_event = None

    def _queue_chunks(
        self,
        request: _SpeechRequest,
        session: AdaptiveSpeechSession,
        prepared: _PreparedSegment,
        audio_session: PcmPlaybackSession,
    ) -> int:
        buffered_frames = 0
        while not self._is_superseded(request.generation):
            buffered_frames = self._queue_segment_audio(request, audio_session, prepared)
            self._report_queued_chunk(request.generation, session, prepared, buffered_frames)
            if not session.remaining_characters:
                return buffered_frames
            if prepared.pause_after:
                frames = round(self._config.structure_pause_seconds * self._sample_rate)
                if frames:
                    result = audio_session.submit_bounded(b"\0\0" * frames)
                    buffered_frames = result.buffered_frames_after_submit
            if not session.advance(buffered_frames / self._sample_rate):
                return buffered_frames
            prepared = self._prepare_chunk(session)
        return buffered_frames

    def _prepare_chunk(self, session: AdaptiveSpeechSession) -> _PreparedSegment:
        prepared = self._synthesize_segment(session.decision.segment)
        session.record_generation(prepared.synthesis_ms / 1000)
        return prepared

    def _queue_segment_audio(
        self, request: _SpeechRequest, audio_session: PcmPlaybackSession, prepared: _PreparedSegment
    ) -> int:
        boundaries = tuple(
            pcm_boundary_from_codepoints(
                request.text,
                round((boundary.seconds + prepared.leading_silence_seconds) * self._sample_rate),
                prepared.offset + boundary.position,
                boundary.length,
            )
            for boundary in estimate_word_boundaries(prepared.spoken, prepared.spoken_seconds)
        )
        return audio_session.submit_bounded(prepared.pcm, boundaries).buffered_frames_after_submit

    def _report_queued_chunk(
        self,
        generation: int,
        session: AdaptiveSpeechSession,
        prepared: _PreparedSegment,
        buffered_frames: int,
    ) -> None:
        emit_speech_debug(
            session.debug_event(prepared.synthesis_ms / 1000, prepared.audio_seconds),
            getattr(self, "_debug_callback", None),
            None,
            byte_offset=0,
        )
        logger.info(
            "supertonic.segment.queued generation=%s segment_index=%s remaining_characters=%s "
            "audio_seconds=%s synthesis_ms=%s buffered_seconds=%s",
            generation,
            session.index,
            session.remaining_characters,
            round(prepared.audio_seconds, 3),
            prepared.synthesis_ms,
            round(buffered_frames / self._sample_rate, 3),
        )

    def _synthesize_segment(self, segment: SpeechSegment) -> _PreparedSegment:
        started_at = time.monotonic()
        with self._synthesis_lock:
            waveform, _durations = self._tts.synthesize(
                text=segment.text,
                lang=self._config.supertonic_language,
                voice_style=self._style,
                total_steps=self._config.supertonic_steps,
                speed=self._config.supertonic_speed,
                silence_duration=0.0,
            )
        audio, leading, spoken_seconds = normalize_edge_silence(
            np.asarray(waveform, dtype=np.float32), self._sample_rate
        )
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        synthesis_ms = round((time.monotonic() - started_at) * 1000)
        logger.info(
            "supertonic.segment.synthesized text_length=%s audio_seconds=%s synthesis_ms=%s pause_after=%s",
            len(segment.text),
            round(audio.size / self._sample_rate, 3),
            synthesis_ms,
            segment.pause_after,
        )
        return _PreparedSegment(
            offset=segment.offset,
            spoken=segment.text,
            pcm=pcm,
            audio_seconds=audio.size / self._sample_rate,
            leading_silence_seconds=leading,
            spoken_seconds=spoken_seconds,
            synthesis_ms=synthesis_ms,
            pause_after=segment.pause_after,
        )

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
            terminal_event = self._terminal_event
        if terminal_event is not None:
            terminal_event.set()

    def _current_audio_session(self) -> PcmPlaybackSession | None:
        with self._session_lock:
            return self._audio_session

    def _stop_active(self, reason: TerminalStatus) -> None:
        if session := self._current_audio_session():
            try:
                session.stop(reason)
            except RuntimeError:
                pass

    def _is_superseded(self, generation: int) -> bool:
        return not self._playback.is_current(generation)
