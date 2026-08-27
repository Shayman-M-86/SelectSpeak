from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

from ..diagnostics import text_preview
from .debug import SpeechDebugEvent
from .segments import (
    MAX_ADAPTIVE_CHUNK_CHARACTERS,
    AdaptiveSpeechChunker,
    SpeechSegment,
)

FIRST_CHUNK_TARGET_CHARACTERS = 100
MIN_CHUNK_CHARACTERS = 30
LOW_RUNWAY_CHUNK_CHARACTERS = 90
MEDIUM_RUNWAY_CHUNK_CHARACTERS = 120
MAX_TARGET_CHUNK_CHARACTERS = 140
HARD_MAX_CHUNK_CHARACTERS = MAX_ADAPTIVE_CHUNK_CHARACTERS
RUNWAY_SAFETY_FACTOR = 0.68
DEFAULT_SYNTHESIS_FIXED_SECONDS = 0.35
DEFAULT_SYNTHESIS_SECONDS_PER_CHARACTER = 0.025

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GenerationStatistics:
    """Online predictor shared by every PCM-producing speech backend."""

    synthesis_fixed_seconds: float = DEFAULT_SYNTHESIS_FIXED_SECONDS
    synthesis_seconds_per_character: float = DEFAULT_SYNTHESIS_SECONDS_PER_CHARACTER
    observations: int = 0

    def record(self, text_length: int, synthesis_seconds: float) -> None:
        if text_length <= 0:
            return
        weight = 0.35 if self.observations else 0.65
        variable_synthesis = max(0.0, synthesis_seconds - self.synthesis_fixed_seconds)
        synthesis_rate = variable_synthesis / text_length
        self.synthesis_seconds_per_character = _blend(
            self.synthesis_seconds_per_character, synthesis_rate, weight
        )
        predicted_variable = self.synthesis_seconds_per_character * text_length
        observed_fixed = max(0.0, synthesis_seconds - predicted_variable)
        self.synthesis_fixed_seconds = _blend(self.synthesis_fixed_seconds, observed_fixed, weight * 0.5)
        self.observations += 1

    def choose_target_characters(self, playback_runway: float) -> int:
        available = max(0.0, playback_runway) * RUNWAY_SAFETY_FACTOR
        variable_budget = max(0.0, available - self.synthesis_fixed_seconds)
        predicted = round(variable_budget / max(0.001, self.synthesis_seconds_per_character))
        if playback_runway < 1.0:
            ceiling = LOW_RUNWAY_CHUNK_CHARACTERS
        elif playback_runway < 4.0:
            ceiling = MEDIUM_RUNWAY_CHUNK_CHARACTERS
        else:
            ceiling = MAX_TARGET_CHUNK_CHARACTERS
        return max(MIN_CHUNK_CHARACTERS, min(ceiling, predicted))

    def estimate_synthesis_seconds(self, text_length: int) -> float:
        return self.synthesis_fixed_seconds + (self.synthesis_seconds_per_character * max(0, text_length))


@dataclass(frozen=True, slots=True)
class ChunkDecision:
    segment: SpeechSegment
    target_characters: int
    playback_runway: float
    predicted_synthesis_seconds: float


class AdaptiveSpeechPipeline:
    """Shared feedback controller for text chunking and synthesis runway."""

    def __init__(
        self,
        text: str,
        statistics: GenerationStatistics | None = None,
    ) -> None:
        self._chunker = AdaptiveSpeechChunker(text)
        self.statistics = statistics or GenerationStatistics()
        self._first = True

    @property
    def remaining_characters(self) -> int:
        return self._chunker.remaining_characters

    def choose_next(self, playback_runway: float = 0.0) -> ChunkDecision | None:
        if self._first:
            target = FIRST_CHUNK_TARGET_CHARACTERS
        else:
            target = self.statistics.choose_target_characters(playback_runway)

        segment = self._chunker.next_chunk(
            target_characters=target,
            hard_max_characters=HARD_MAX_CHUNK_CHARACTERS,
        )
        if segment is None:
            return None
        self._first = False
        return ChunkDecision(
            segment=segment,
            target_characters=target,
            playback_runway=playback_runway,
            predicted_synthesis_seconds=self.statistics.estimate_synthesis_seconds(len(segment.text)),
        )

    def record_generation(self, segment: SpeechSegment, synthesis_seconds: float) -> None:
        self.statistics.record(len(segment.text), synthesis_seconds)


class AdaptiveSpeechSession:
    """Coordinate adaptive chunks shared by streaming speech backends."""

    def __init__(
        self,
        backend: str,
        pipeline: AdaptiveSpeechPipeline,
        decision: ChunkDecision,
    ) -> None:
        self.backend = backend
        self.pipeline = pipeline
        self.decision = decision
        self.index = 0

    @classmethod
    def start(
        cls,
        text: str,
        backend: str,
        statistics: GenerationStatistics,
    ) -> Self | None:
        pipeline = AdaptiveSpeechPipeline(text, statistics)
        decision = pipeline.choose_next()
        return cls(backend, pipeline, decision) if decision is not None else None

    @property
    def remaining_characters(self) -> int:
        return self.pipeline.remaining_characters

    def record_generation(self, synthesis_seconds: float) -> None:
        self.pipeline.record_generation(self.decision.segment, synthesis_seconds)

    def debug_event(self, synthesis_seconds: float, audio_seconds: float) -> SpeechDebugEvent:
        segment = self.decision.segment
        return SpeechDebugEvent(
            kind="chunk_ready",
            backend=self.backend,
            chunk_index=self.index,
            text_offset=segment.offset,
            text_length=len(segment.text),
            target_characters=self.decision.target_characters,
            predicted_synthesis_ms=round(self.decision.predicted_synthesis_seconds * 1000),
            actual_synthesis_ms=round(synthesis_seconds * 1000),
            audio_ms=round(audio_seconds * 1000),
            runway_ms=round(self.decision.playback_runway * 1000),
            boundary="sentence/structure" if segment.pause_after else "technical",
        )

    def queue_structure_pause(self, feed_silence: Callable[[float], None], pause_seconds: float) -> None:
        if not self.decision.segment.pause_after:
            return
        feed_silence(pause_seconds)
        logger.debug(
            "speech.structure_pause.queued backend=%s configured_ms=%s segment_index=%s",
            self.backend,
            round(pause_seconds * 1000),
            self.index,
        )

    def advance(self, playback_runway: float) -> bool:
        decision = self.pipeline.choose_next(playback_runway)
        if decision is None:
            return False
        self.index += 1
        self.decision = decision
        logger.debug(
            "speech.chunk.selected backend=%s segment_index=%s target_characters=%s "
            "actual_characters=%s playback_runway=%s observations=%s text_preview=%s",
            self.backend,
            self.index,
            decision.target_characters,
            len(decision.segment.text),
            round(playback_runway, 3),
            self.pipeline.statistics.observations,
            text_preview(decision.segment.text),
        )
        return True


def _blend(previous: float, observed: float, weight: float) -> float:
    return previous * (1.0 - weight) + observed * weight
