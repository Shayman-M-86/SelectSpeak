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
from .pcm import (
    PcmBoundary,
    PcmEvent,
    PcmEventCallback,
    PcmFormat,
    PcmPlaybackSession,
    PcmPlayedWord,
    PcmSampleFormat,
    PcmStarted,
    PcmSubmitResult,
    PcmTerminal,
    PcmUnderrun,
    pcm_boundary_from_codepoints,
    utf16_code_unit_offset,
)

__all__ = [
    "Speaker",
    "PcmBoundary",
    "PcmEvent",
    "PcmEventCallback",
    "PcmFormat",
    "PcmPlaybackSession",
    "PcmPlayedWord",
    "PcmSampleFormat",
    "PcmStarted",
    "PcmSubmitResult",
    "PcmTerminal",
    "PcmUnderrun",
    "SpeechEvent",
    "SpeechEventCallback",
    "SpeechStarted",
    "SpeechTerminal",
    "SpeechWord",
    "TerminalStatus",
    "create_speaker",
    "pcm_boundary_from_codepoints",
    "utf16_code_unit_offset",
]
