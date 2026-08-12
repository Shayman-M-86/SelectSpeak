"""Structured diagnostics emitted by speech generation and playback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class SpeechDebugEvent:
    kind: str
    backend: str
    chunk_index: int | None = None
    text_offset: int = 0
    text_length: int = 0
    target_characters: int | None = None
    predicted_synthesis_ms: int | None = None
    actual_synthesis_ms: int | None = None
    audio_ms: int | None = None
    runway_ms: int | None = None
    queue_delay_ms: int | None = None
    delay_ms: int | None = None
    boundary: str = ""
    message: str = ""


SpeechDebugCallback = Callable[[SpeechDebugEvent], None]


def with_queue_delay(
    event: SpeechDebugEvent, generated_at: float, played_at: float
) -> SpeechDebugEvent:
    return replace(
        event,
        kind="chunk_playing",
        queue_delay_ms=round(max(0.0, played_at - generated_at) * 1000),
    )
