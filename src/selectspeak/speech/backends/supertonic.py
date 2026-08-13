from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass

import numpy as np
from supertonic import TTS

from ...config import SpeechConfig
from ...runtime_paths import model_dir
from ..contracts import WordCallback
from ..debug import SpeechDebugCallback, emit_speech_debug
from ..pipeline import AdaptiveSpeechSession, GenerationStatistics
from ..playback import PlaybackController, SpeechRequest
from ..segments import SpeechSegment
from ..waveout import TICKS_PER_SECOND, WaveOutPlayer

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44_100
_WORD_PATTERN = re.compile(r"[\w]+(?:[’'-][\w]+)*", re.UNICODE)
EDGE_PADDING_SECONDS = 0.015
LEADING_SCAN_SECONDS = 0.5
TRAILING_SCAN_SECONDS = 0.75
MAX_BUFFERED_AUDIO_SECONDS = 12.0


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
        word_callback: WordCallback | None = None,
        debug_callback: SpeechDebugCallback | None = None,
    ) -> None:
        self._config = config
        self._word_callback = word_callback
        self._debug_callback = debug_callback
        self._playback = PlaybackController()
        # A cancelled inference cannot be interrupted by the Supertonic API.
        # Serialize it with the next request so two ONNX runs cannot contend
        # for the CPU and turn a cancellation into a large startup outlier.
        self._synthesis_lock = threading.Lock()
        self._request_text = ""
        self._generation_statistics = GenerationStatistics()
        logger.info("supertonic.model.loading")
        self._tts = TTS(model_dir=model_dir("supertonic3"), auto_download=True)
        self._style = self._tts.get_voice_style(config.supertonic_voice)
        self._sample_rate = int(getattr(self._tts, "sample_rate", SAMPLE_RATE))
        self._player = WaveOutPlayer(
            self._on_played_word,
            config.speech_volume,
            sample_rate=self._sample_rate,
            backend_name="supertonic",
            debug_callback=debug_callback,
        )
        self._thread = threading.Thread(target=self._run, daemon=True, name="SupertonicSpeaker")
        self._thread.start()
        logger.info(
            "supertonic.model.loaded voice=%s language=%s sample_rate=%s",
            config.supertonic_voice,
            config.supertonic_language,
            self._sample_rate,
        )

    def speak(self, text: str) -> int | None:
        if len(text) < self._config.minimum_text_length:
            return None
        request, active = self._playback.submit(text)
        if active:
            self._player.stop()
        return request.generation

    def stop(self) -> None:
        _generation, active = self._playback.cancel()
        if active:
            self._player.stop()

    def pause(self) -> None:
        if self._playback.pause_now():
            self._player.pause()

    def resume(self) -> None:
        if self._playback.resume_now():
            self._player.resume()

    def wait_until_done(self, generation: int) -> bool:
        return self._playback.wait_until_done(generation)

    def _run(self) -> None:
        while True:
            request = self._playback.next_request()
            if not self._playback.is_current(request.generation):
                continue
            try:
                self._speak_request(request)
            except Exception:
                logger.exception("supertonic.request.failed generation=%s", request.generation)
                self._playback.fail(request.generation)
                return

    def _speak_request(self, request: _SpeechRequest) -> None:
        if not self._playback.begin(request.generation):
            return
        try:
            self._synthesize_request(request)
        finally:
            self._playback.complete(request.generation)

    def _synthesize_request(self, request: _SpeechRequest) -> None:
        session = AdaptiveSpeechSession.start(request.text, "supertonic", self._generation_statistics)
        if session is None:
            return
        prepared = self._prepare_chunk(session)
        if self._is_superseded(request.generation):
            return
        self._request_text = request.text
        self._player.start()
        try:
            self._queue_chunks(request.generation, session, prepared)
        finally:
            self._player.finish()

    def _queue_chunks(
        self,
        generation: int,
        session: AdaptiveSpeechSession,
        prepared: _PreparedSegment,
    ) -> None:
        while not self._is_superseded(generation):
            audio_base = self._queue_segment_audio(prepared)
            self._report_queued_chunk(generation, session, prepared, audio_base)
            if not session.remaining_characters:
                return
            session.queue_structure_pause(self._player.feed_silence, self._config.structure_pause_seconds)
            if not self._wait_for_buffer_capacity(generation):
                return
            if not session.advance(self._player.buffered_seconds):
                return
            prepared = self._prepare_chunk(session)

    def _prepare_chunk(self, session: AdaptiveSpeechSession) -> _PreparedSegment:
        prepared = self._synthesize_segment(session.decision.segment)
        session.record_generation(prepared.synthesis_ms / 1000)
        return prepared

    def _queue_segment_audio(self, prepared: _PreparedSegment) -> int:
        audio_base = self._player.fed_bytes
        for boundary in estimate_word_boundaries(prepared.spoken, prepared.spoken_seconds):
            self._player.add_boundary(
                round((boundary.seconds + prepared.leading_silence_seconds) * TICKS_PER_SECOND),
                prepared.offset + boundary.position,
                boundary.length,
                base_byte_offset=audio_base,
            )
        self._player.feed(prepared.pcm)
        return audio_base

    def _report_queued_chunk(
        self,
        generation: int,
        session: AdaptiveSpeechSession,
        prepared: _PreparedSegment,
        audio_base: int,
    ) -> None:
        emit_speech_debug(
            session.debug_event(prepared.synthesis_ms / 1000, prepared.audio_seconds),
            getattr(self, "_debug_callback", None),
            getattr(self._player, "add_debug_marker", None),
            byte_offset=audio_base,
        )
        logger.info(
            "supertonic.segment.queued generation=%s segment_index=%s remaining_characters=%s "
            "audio_seconds=%s synthesis_ms=%s buffered_seconds=%s",
            generation,
            session.index,
            session.remaining_characters,
            round(prepared.audio_seconds, 3),
            prepared.synthesis_ms,
            round(self._player.buffered_seconds, 3),
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

    def _on_played_word(self, position: int, length: int) -> None:
        if self._word_callback:
            self._word_callback(self._request_text, position, length)

    def _wait_for_buffer_capacity(self, generation: int) -> bool:
        while self._player.buffered_seconds > MAX_BUFFERED_AUDIO_SECONDS:
            if self._is_superseded(generation):
                return False
            time.sleep(0.02)
        return True

    def _is_superseded(self, generation: int) -> bool:
        return not self._playback.is_current(generation)
