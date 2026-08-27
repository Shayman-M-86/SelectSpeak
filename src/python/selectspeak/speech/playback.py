from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum, auto
from queue import Empty
from typing import Final

from .contracts import (
    SpeechEvent,
    SpeechEventCallback,
    SpeechStarted,
    SpeechTerminal,
    SpeechWord,
    TerminalStatus,
)

logger = logging.getLogger(__name__)

UINT64_MAX: Final = (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    request_id: int
    generation: int
    text: str
    callback: SpeechEventCallback


class PlaybackCommand(Enum):
    NONE = auto()
    PAUSE = auto()
    RESUME = auto()


class PlaybackController:
    """Own the thread-safe request lifecycle shared by speech backends.

    Generations remain private worker-cancellation tokens. Application-issued
    request IDs are the immutable public identity and every accepted request is
    delivered through the controller's single ordered event path.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._delivery_lock = threading.RLock()
        self._pending_request: SpeechRequest | None = None
        self._active_request: SpeechRequest | None = None
        self._generation = 0
        self._last_request_id = 0
        self._pending_command = PlaybackCommand.NONE
        self._paused = False
        self._failed = False
        self._closed = False

    @property
    def active(self) -> bool:
        with self._condition:
            return self._current_request_locked() is not None

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    @property
    def generation(self) -> int:
        with self._condition:
            return self._generation

    def submit(
        self,
        request_id: int,
        text: str,
        callback: SpeechEventCallback,
    ) -> tuple[SpeechRequest, bool]:
        if not 0 < request_id <= UINT64_MAX:
            raise ValueError("request_id must be an unsigned 64-bit integer greater than zero")
        with self._delivery_lock:
            deliveries: list[tuple[SpeechEventCallback, SpeechEvent]] = []
            with self._condition:
                if self._closed:
                    raise RuntimeError("The speech backend is closed")
                if self._failed:
                    raise RuntimeError("The speech worker has failed")
                if request_id <= self._last_request_id:
                    raise ValueError("request_id must increase monotonically")
                self._last_request_id = request_id
                was_active = self._current_request_locked() is not None
                self._settle_current_locked(TerminalStatus.SUPERSEDED, deliveries)
                self._generation += 1
                request = SpeechRequest(request_id, self._generation, text, callback)
                self._pending_request = request
                self._pending_command = PlaybackCommand.NONE
                deliveries.append((request.callback, SpeechStarted(request_id)))
                self._condition.notify_all()
            self._deliver(deliveries)
            return request, was_active

    def cancel(self) -> tuple[int, bool]:
        with self._delivery_lock:
            deliveries: list[tuple[SpeechEventCallback, SpeechEvent]] = []
            with self._condition:
                if self._closed:
                    return self._generation, False
                was_active = self._current_request_locked() is not None
                self._settle_current_locked(TerminalStatus.CANCELLED, deliveries)
                self._generation += 1
                self._condition.notify_all()
                generation = self._generation
            self._deliver(deliveries)
            return generation, was_active

    def next_request(self, timeout: float | None = None) -> SpeechRequest | None:
        with self._condition:
            ready = self._condition.wait_for(
                lambda: self._pending_request is not None or self._failed or self._closed,
                timeout,
            )
            if not ready:
                raise Empty
            request = self._pending_request
            self._pending_request = None
            self._active_request = request
            return request

    def close(self) -> bool:
        """Reject new work, close the current request, and wake the worker."""
        with self._delivery_lock:
            deliveries: list[tuple[SpeechEventCallback, SpeechEvent]] = []
            with self._condition:
                if self._closed:
                    return False
                self._closed = True
                was_active = self._current_request_locked() is not None
                self._settle_current_locked(TerminalStatus.CLOSED, deliveries)
                self._generation += 1
                self._condition.notify_all()
            self._deliver(deliveries)
            return was_active

    def complete(self, generation: int) -> None:
        with self._delivery_lock:
            deliveries: list[tuple[SpeechEventCallback, SpeechEvent]] = []
            with self._condition:
                request = self._active_request
                if request is not None and request.generation == generation:
                    self._settle_current_locked(TerminalStatus.COMPLETED, deliveries)
                self._condition.notify_all()
            self._deliver(deliveries)

    def fail(self, generation: int | None = None) -> None:
        with self._delivery_lock:
            deliveries: list[tuple[SpeechEventCallback, SpeechEvent]] = []
            with self._condition:
                self._failed = True
                if generation is None or self._is_current_locked(generation):
                    self._settle_current_locked(TerminalStatus.FAILED, deliveries)
                self._condition.notify_all()
            self._deliver(deliveries)

    def played_word(self, generation: int, position: int, length: int) -> None:
        with self._delivery_lock:
            with self._condition:
                request = self._active_request
                if request is None or request.generation != generation:
                    return
                event = SpeechWord(request.request_id, request.text, position, length)
            self._deliver([(request.callback, event)])

    def is_current(self, generation: int) -> bool:
        with self._condition:
            return self._is_current_locked(generation)

    def request_pause(self) -> bool:
        with self._condition:
            if self._active_request is None or self._paused:
                return False
            self._pending_command = PlaybackCommand.PAUSE
            return True

    def request_resume(self) -> bool:
        with self._condition:
            if not self._paused:
                return False
            self._pending_command = PlaybackCommand.RESUME
            return True

    def pause_now(self) -> bool:
        with self._condition:
            if self._active_request is None or self._paused:
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
            command = self._pending_command
            self._pending_command = PlaybackCommand.NONE
            if command is PlaybackCommand.PAUSE:
                self._paused = True
                return PlaybackCommand.PAUSE
            if command is PlaybackCommand.RESUME:
                if self._paused:
                    self._paused = False
                    return PlaybackCommand.RESUME
            return PlaybackCommand.NONE

    def _is_current_locked(self, generation: int) -> bool:
        request = self._current_request_locked()
        return request is not None and request.generation == generation

    def _current_request_locked(self) -> SpeechRequest | None:
        return self._active_request or self._pending_request

    def _settle_current_locked(
        self,
        status: TerminalStatus,
        deliveries: list[tuple[SpeechEventCallback, SpeechEvent]],
    ) -> None:
        request = self._current_request_locked()
        if request is None:
            return
        self._pending_request = None
        self._active_request = None
        self._pending_command = PlaybackCommand.NONE
        self._paused = False
        deliveries.append((request.callback, SpeechTerminal(request.request_id, status)))

    @staticmethod
    def _deliver(deliveries: list[tuple[SpeechEventCallback, SpeechEvent]]) -> None:
        for callback, event in deliveries:
            try:
                callback(event)
            except Exception:
                logger.exception(
                    "speech.event_callback.failed request_id=%s event=%s",
                    event.request_id,
                    type(event).__name__,
                )
