from __future__ import annotations

from dataclasses import dataclass

from .segments import AdaptiveSpeechChunker, SpeechSegment

FIRST_CHUNK_TARGET_CHARACTERS = 100
MIN_CHUNK_CHARACTERS = 30
HEALTHY_CHUNK_CHARACTERS = 300
HARD_MAX_CHUNK_CHARACTERS = 500
MAX_SENTENCES_PER_CHUNK = 2
STARTUP_CHUNK_GROWTH_LIMIT = 2.0
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
            ceiling = 90
        elif playback_runway < 4.0:
            ceiling = HEALTHY_CHUNK_CHARACTERS
        else:
            ceiling = HARD_MAX_CHUNK_CHARACTERS
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
    allow_colon: bool
    allow_comma: bool
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
        self._chunk_index = 0
        self._previous_chunk_characters = 0

    @property
    def remaining_characters(self) -> int:
        return self._chunker.remaining_characters

    def choose_next(self, playback_runway: float = 0.0) -> ChunkDecision | None:
        if self._first:
            target = FIRST_CHUNK_TARGET_CHARACTERS
            allow_colon = True
            allow_comma = True
            hard_max = HARD_MAX_CHUNK_CHARACTERS
        else:
            target = self.statistics.choose_target_characters(playback_runway)
            allow_colon = playback_runway < 4.0
            allow_comma = playback_runway < 1.5
            hard_max = HARD_MAX_CHUNK_CHARACTERS
            if self._chunk_index == 1:
                # The first chunk is deliberately latency-oriented. Do not let
                # the immediately following synthesis call dwarf the amount of
                # audio it has available as runway.
                startup_cap = max(
                    1,
                    round(
                        self._previous_chunk_characters
                        * STARTUP_CHUNK_GROWTH_LIMIT
                    ),
                )
                hard_max = min(hard_max, startup_cap)
                target = min(target, hard_max)
                allow_colon = True
                allow_comma = True

        segment = self._chunker.next_chunk(
            target_characters=target,
            hard_max_characters=hard_max,
            max_sentences=MAX_SENTENCES_PER_CHUNK,
            allow_colon=allow_colon,
            allow_comma=allow_comma,
        )
        if segment is None:
            return None
        self._first = False
        self._previous_chunk_characters = len(segment.text)
        self._chunk_index += 1
        return ChunkDecision(
            segment=segment,
            target_characters=target,
            playback_runway=playback_runway,
            allow_colon=allow_colon,
            allow_comma=allow_comma,
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
