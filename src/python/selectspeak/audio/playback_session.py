from __future__ import annotations

import threading
from dataclasses import dataclass

from ..speech.contracts import Speaker


@dataclass(frozen=True, slots=True)
class PlaybackSnapshot:
    text: str
    generation: int | None
    speaker: Speaker | None
    speaking: bool
    paused: bool
    started_at: float
    ended_at: float
    source: str


# This state-transition code is clearer with related snapshot fields grouped by row.
# fmt: off
class PlaybackSession:
    """Own application playback state independently of any one backend."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot = PlaybackSnapshot("", None, None, False, False, 0.0, 0.0, "")

    def snapshot(self) -> PlaybackSnapshot:
        with self._lock:
            return self._snapshot

    def start(
        self, speaker: Speaker, generation: int,
        text: str, source: str, started_at: float,
    ) -> None:
        with self._lock:
            self._snapshot = PlaybackSnapshot(
                text, generation, speaker,
                True, False, started_at,
                float("inf"), source,
            )

    def stop(self, fallback: Speaker, ended_at: float) -> tuple[Speaker, str]:
        with self._lock:
            current = self._snapshot
            speaker = current.speaker or fallback
            self._snapshot = PlaybackSnapshot(
                current.text, None, None,
                False, False, current.started_at,
                ended_at, current.source,
            )
            return speaker, current.text

    def pause(self, fallback: Speaker) -> tuple[Speaker, str] | None:
        with self._lock:
            current = self._snapshot
            if not current.speaking or current.paused:
                return None
            self._snapshot = PlaybackSnapshot(
                current.text, current.generation, current.speaker,
                True, True, current.started_at,
                current.ended_at, current.source,
            )
            return current.speaker or fallback, current.text

    def resume(self, fallback: Speaker) -> tuple[Speaker, str] | None:
        with self._lock:
            current = self._snapshot
            if not current.speaking or not current.paused:
                return None
            self._snapshot = PlaybackSnapshot(
                current.text, current.generation, current.speaker,
                True, False, current.started_at,
                current.ended_at, current.source,
            )
            return current.speaker or fallback, current.text

    def complete(self, speaker: Speaker, generation: int, ended_at: float) -> bool:
        with self._lock:
            current = self._snapshot
            if current.generation != generation or current.speaker is not speaker:
                return False
            self._snapshot = PlaybackSnapshot(
                current.text, None, None,
                False, False, current.started_at,
                ended_at, current.source,
            )
            return True
# fmt: on
