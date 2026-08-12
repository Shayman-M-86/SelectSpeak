from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass

import numpy as np
from supertonic import TTS

from ...config import SpeechConfig
from ...logging_setup import log_event, log_exception, text_preview
from ..contracts import WordCallback
from ..debug import SpeechDebugCallback, SpeechDebugEvent
from ..pipeline import AdaptiveSpeechPipeline, GenerationStatistics
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
    active_start = (
        int(prefix_active[0]) * window_size if prefix_active.size else 0
    )

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
        log_event(logger, logging.INFO, "supertonic.model.loading")
        self._tts = TTS(auto_download=True)
        self._style = self._tts.get_voice_style(config.supertonic_voice)
        self._sample_rate = int(getattr(self._tts, "sample_rate", SAMPLE_RATE))
        self._player = WaveOutPlayer(
            self._on_played_word,
            config.speech_volume,
            sample_rate=self._sample_rate,
            backend_name="supertonic",
            debug_callback=debug_callback,
        )
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="SupertonicSpeaker"
        )
        self._thread.start()
        log_event(
            logger,
            logging.INFO,
            "supertonic.model.loaded",
            voice=config.supertonic_voice,
            language=config.supertonic_language,
            sample_rate=self._sample_rate,
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
                log_exception(
                    logger,
                    "supertonic.request.failed",
                    generation=request.generation,
                )
                self._playback.fail(request.generation)
                return

    def _speak_request(self, request: _SpeechRequest) -> None:
        if not self._playback.begin(request.generation):
            return
        player_started = False
        try:
            pipeline = AdaptiveSpeechPipeline(
                request.text, self._generation_statistics
            )
            decision = pipeline.choose_next()
            if decision is None:
                return
            prepared = self._synthesize_segment(decision.segment)
            pipeline.record_generation(
                decision.segment, prepared.synthesis_ms / 1000
            )
            if self._is_superseded(request.generation):
                return
            self._request_text = request.text
            self._player.start()
            player_started = True
            index = 0
            while True:
                if self._is_superseded(request.generation):
                    return
                audio_base = self._player.fed_bytes
                for boundary in estimate_word_boundaries(
                    prepared.spoken, prepared.spoken_seconds
                ):
                    self._player.add_boundary(
                        round(
                            (
                                boundary.seconds
                                + prepared.leading_silence_seconds
                            )
                            * TICKS_PER_SECOND
                        ),
                        prepared.offset + boundary.position,
                        boundary.length,
                        base_byte_offset=audio_base,
                    )
                self._player.feed(prepared.pcm)
                debug_event = SpeechDebugEvent(
                        kind="chunk_ready",
                        backend="supertonic",
                        chunk_index=index,
                        text_offset=prepared.offset,
                        text_length=len(prepared.spoken),
                        target_characters=decision.target_characters,
                        predicted_synthesis_ms=round(
                            decision.predicted_synthesis_seconds * 1000
                        ),
                        actual_synthesis_ms=prepared.synthesis_ms,
                        audio_ms=round(prepared.audio_seconds * 1000),
                        runway_ms=round(decision.playback_runway * 1000),
                        boundary=(
                            "sentence/structure"
                            if prepared.pause_after
                            else "technical"
                        ),
                    )
                debug_callback = getattr(self, "_debug_callback", None)
                if debug_callback:
                    debug_callback(debug_event)
                add_debug_marker = getattr(self._player, "add_debug_marker", None)
                if add_debug_marker:
                    add_debug_marker(audio_base, debug_event)
                log_event(
                    logger,
                    logging.INFO,
                    "supertonic.segment.queued",
                    generation=request.generation,
                    segment_index=index,
                    remaining_characters=pipeline.remaining_characters,
                    audio_seconds=round(prepared.audio_seconds, 3),
                    synthesis_ms=prepared.synthesis_ms,
                    buffered_seconds=round(self._player.buffered_seconds, 3),
                )
                if not pipeline.remaining_characters:
                    break
                if prepared.pause_after:
                    self._player.feed_silence(
                        self._config.structure_pause_seconds
                    )
                if not self._wait_for_buffer_capacity(request.generation):
                    return
                runway = self._player.buffered_seconds
                decision = pipeline.choose_next(runway)
                if decision is None:
                    break
                log_event(
                    logger,
                    logging.DEBUG,
                    "supertonic.chunk.selected",
                    segment_index=index + 1,
                    target_characters=decision.target_characters,
                    actual_characters=len(decision.segment.text),
                    playback_runway=round(runway, 3),
                    allow_colon=decision.allow_colon,
                    allow_comma=decision.allow_comma,
                    observations=pipeline.statistics.observations,
                    text_preview=text_preview(decision.segment.text),
                )
                prepared = self._synthesize_segment(decision.segment)
                pipeline.record_generation(
                    decision.segment, prepared.synthesis_ms / 1000
                )
                index += 1
        finally:
            if player_started:
                self._player.finish()
            self._playback.complete(request.generation)

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
        log_event(
            logger,
            logging.INFO,
            "supertonic.segment.synthesized",
            text_length=len(segment.text),
            audio_seconds=round(audio.size / self._sample_rate, 3),
            synthesis_ms=synthesis_ms,
            pause_after=segment.pause_after,
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
