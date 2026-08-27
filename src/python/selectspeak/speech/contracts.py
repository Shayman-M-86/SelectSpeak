from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol


class TerminalStatus(IntEnum):
    NONE = 0
    COMPLETED = 1
    CANCELLED = 2
    SUPERSEDED = 3
    FAILED = 4
    CLOSED = 5


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    request_id: int


@dataclass(frozen=True, slots=True)
class SpeechWord:
    request_id: int
    text: str
    position: int
    length: int


@dataclass(frozen=True, slots=True)
class SpeechTerminal:
    request_id: int
    status: TerminalStatus


SpeechEvent = SpeechStarted | SpeechWord | SpeechTerminal
SpeechEventCallback = Callable[[SpeechEvent], None]


class Speaker(Protocol):
    def speak(self, request_id: int, text: str, callback: SpeechEventCallback) -> bool: ...

    def stop(self) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def close(self) -> None: ...
