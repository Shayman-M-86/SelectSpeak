from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(slots=True)
class GenerationStatistics:
    """Online predictor shared by every PCM-producing speech backend."""

    synthesis_fixed_seconds: float = DEFAULT_SYNTHESIS_FIXED_SECONDS
    synthesis_seconds_per_character: float = (
        DEFAULT_SYNTHESIS_SECONDS_PER_CHARACTER
    )
    observations: int = 0

    def record(self, text_length: int, synthesis_seconds: float) -> None:
        if text_length <= 0:
            return
        weight = 0.35 if self.observations else 0.65
        variable_synthesis = max(
            0.0, synthesis_seconds - self.synthesis_fixed_seconds
        )
        synthesis_rate = variable_synthesis / text_length
        self.synthesis_seconds_per_character = _blend(
            self.synthesis_seconds_per_character, synthesis_rate, weight
        )
        predicted_variable = self.synthesis_seconds_per_character * text_length
        observed_fixed = max(0.0, synthesis_seconds - predicted_variable)
        self.synthesis_fixed_seconds = _blend(
            self.synthesis_fixed_seconds, observed_fixed, weight * 0.5
        )
        self.observations += 1

    def choose_target_characters(self, playback_runway: float) -> int:
        available = max(0.0, playback_runway) * RUNWAY_SAFETY_FACTOR
        variable_budget = max(0.0, available - self.synthesis_fixed_seconds)
        predicted = round(
            variable_budget / max(0.001, self.synthesis_seconds_per_character)
        )
        if playback_runway < 1.0:
            ceiling = LOW_RUNWAY_CHUNK_CHARACTERS
        elif playback_runway < 4.0:
            ceiling = MEDIUM_RUNWAY_CHUNK_CHARACTERS
        else:
            ceiling = MAX_TARGET_CHUNK_CHARACTERS
        return max(MIN_CHUNK_CHARACTERS, min(ceiling, predicted))

    def estimate_synthesis_seconds(self, text_length: int) -> float:
        return self.synthesis_fixed_seconds + (
            self.synthesis_seconds_per_character * max(0, text_length)
        )


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
            predicted_synthesis_seconds=self.statistics.estimate_synthesis_seconds(
                len(segment.text)
            ),
        )

    def record_generation(
        self, segment: SpeechSegment, synthesis_seconds: float
    ) -> None:
        self.statistics.record(len(segment.text), synthesis_seconds)


def _blend(previous: float, observed: float, weight: float) -> float:
    return previous * (1.0 - weight) + observed * weight
