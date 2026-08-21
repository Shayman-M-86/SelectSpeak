"""Speech contracts, processing, playback, and backend implementations."""

from .contracts import (
    Speaker,
    SpeechEvent,
    SpeechEventCallback,
    SpeechStarted,
    SpeechTerminal,
    SpeechWord,
    TerminalStatus,
)
from .factory import create_speaker

__all__ = [
    "Speaker",
    "SpeechEvent",
    "SpeechEventCallback",
    "SpeechStarted",
    "SpeechTerminal",
    "SpeechWord",
    "TerminalStatus",
    "create_speaker",
]
