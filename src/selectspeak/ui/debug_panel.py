from __future__ import annotations

from dataclasses import dataclass, field

from ..speech.debug import SpeechDebugEvent


@dataclass(slots=True)
class SpeechDebugPanelModel:
    """Collect and format speech diagnostics independently of Tk widgets."""

    chunks: dict[int, SpeechDebugEvent] = field(default_factory=dict)
    delays: list[SpeechDebugEvent] = field(default_factory=list)
    active: SpeechDebugEvent | None = None

    def update(self, event: SpeechDebugEvent) -> SpeechDebugEvent:
        if event.chunk_index is not None:
            self.chunks[event.chunk_index] = event
        if event.kind == "chunk_playing":
            self.active = event
        if event.kind == "underrun":
            self.delays.append(event)
        return event if event.kind == "underrun" else self.active or event

    def reset(self) -> None:
        self.chunks.clear()
        self.delays.clear()
        self.active = None

    def metrics(self, event: SpeechDebugEvent | None = None) -> tuple[str, bool]:
        if event is None and self.chunks:
            event = self.chunks[max(self.chunks)]
        if event is None:
            return "Speech diagnostics waiting for chunks…", False
        if event.kind == "underrun":
            return (
                f"⚠ UNDERRUN  delay={event.delay_ms or 0}ms  "
                f"runway={event.runway_ms or 0}ms",
                True,
            )
        chunk = (event.chunk_index or 0) + 1
        state = "PLAY" if event.kind == "chunk_playing" else "READY"
        prediction_error = (
            (event.actual_synthesis_ms or 0) - (event.predicted_synthesis_ms or 0)
        )
        ready_ahead = sum(
            item.kind == "chunk_ready"
            and item.chunk_index is not None
            and item.chunk_index > (event.chunk_index or 0)
            for item in self.chunks.values()
        )
        return (
            f"{state} chunk={chunk}  chars={event.text_length}"
            f"/{event.target_characters or 0}  boundary={event.boundary}\n"
            f"synth est={event.predicted_synthesis_ms or 0}ms  "
            f"actual={event.actual_synthesis_ms or 0}ms  "
            f"error={prediction_error:+d}ms  "
            f"audio={event.audio_ms or 0}ms  runway={event.runway_ms or 0}ms  "
            f"queue={event.queue_delay_ms or 0}ms  "
            f"ready={ready_ahead}  underruns={len(self.delays)}",
            False,
        )
