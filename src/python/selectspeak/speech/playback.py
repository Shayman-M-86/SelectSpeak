from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum, auto
from queue import Empty, Queue
from typing import Final


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    generation: int
    text: str


class PlaybackCommand(Enum):
    NONE = auto()
    PAUSE = auto()
    RESUME = auto()


_CLOSE: Final = object()


class PlaybackController:
    """Own the thread-safe request lifecycle shared by speech backends."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._queue: Queue[SpeechRequest | object] = Queue()
        self._generation = 0
        self._active_generation: int | None = None
        self._completed_generation = 0
        self._paused = False
        self._failed = False
        self._closed = False
        self._pause_requested = threading.Event()
        self._resume_requested = threading.Event()

    @property
    def active(self) -> bool:
        with self._condition:
            return self._active_generation is not None

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    @property
    def generation(self) -> int:
        with self._condition:
            return self._generation

    @property
    def completed_generation(self) -> int:
        with self._condition:
            return self._completed_generation

    def submit(self, text: str) -> tuple[SpeechRequest, bool]:
        with self._condition:
            if self._closed:
                raise RuntimeError("The speech backend is closed")
            if self._failed:
                raise RuntimeError("The speech worker has failed")
            self._generation += 1
            request = SpeechRequest(self._generation, text)
            self._drain_queue()
            was_active = self._active_generation is not None
            self._pause_requested.clear()
            self._resume_requested.set()
            self._queue.put(request)
            self._condition.notify_all()
            return request, was_active

    def cancel(self) -> tuple[int, bool]:
        with self._condition:
            if self._closed:
                return self._generation, False
            self._generation += 1
            self._drain_queue()
            was_active = self._active_generation is not None
            self._paused = False
            self._pause_requested.clear()
            self._resume_requested.set()
            self._condition.notify_all()
            return self._generation, was_active

    def next_request(self, timeout: float | None = None) -> SpeechRequest | None:
        item = self._queue.get(timeout=timeout)
        if item is _CLOSE:
            return None
        if not isinstance(item, SpeechRequest):
            raise RuntimeError("Invalid speech request queued")
        return item

    def close(self) -> bool:
        """Reject new work, supersede active work, and wake the worker."""
        with self._condition:
            if self._closed:
                return False
            self._closed = True
            self._generation += 1
            self._drain_queue()
            was_active = self._active_generation is not None
            self._paused = False
            self._pause_requested.clear()
            self._resume_requested.set()
            self._queue.put(_CLOSE)
            self._condition.notify_all()
            return was_active

    def begin(self, generation: int) -> bool:
        with self._condition:
            if generation != self._generation:
                return False
            self._active_generation = generation
            self._paused = False
            return True

    def complete(self, generation: int) -> None:
        with self._condition:
            if self._active_generation == generation:
                self._active_generation = None
                self._paused = False
            if self._generation == generation:
                self._completed_generation = generation
            self._condition.notify_all()

    def fail(self, generation: int | None = None) -> None:
        with self._condition:
            self._failed = True
            if generation is None or self._active_generation == generation:
                self._active_generation = None
                self._paused = False
            self._condition.notify_all()

    def is_current(self, generation: int) -> bool:
        with self._condition:
            return self._generation == generation

    def wait_until_done(self, generation: int) -> bool:
        with self._condition:
            self._condition.wait_for(
                lambda: (
                    self._closed
                    or self._failed
                    or self._generation != generation
                    or self._completed_generation >= generation
                )
            )
            return (
                not self._closed
                and not self._failed
                and self._generation == generation
                and self._completed_generation >= generation
            )

    def request_pause(self) -> bool:
        with self._condition:
            if self._active_generation is None or self._paused:
                return False
            self._pause_requested.set()
            return True

    def request_resume(self) -> bool:
        with self._condition:
            if not self._paused:
                return False
            self._resume_requested.set()
            return True

    def pause_now(self) -> bool:
        with self._condition:
            if self._active_generation is None or self._paused:
                return False
            self._paused = True
            return True

    def resume_now(self) -> bool:
        with self._condition:
            if not self._paused:
                return False
            self._paused = False
            return True

    def consume_command(self) -> PlaybackCommand:
        with self._condition:
            if self._pause_requested.is_set():
                self._pause_requested.clear()
                self._paused = True
                return PlaybackCommand.PAUSE
            if self._resume_requested.is_set():
                self._resume_requested.clear()
                if self._paused:
                    self._paused = False
                    return PlaybackCommand.RESUME
            return PlaybackCommand.NONE

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                return
