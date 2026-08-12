"""Speech contracts, processing, playback, and backend implementations."""

from .contracts import Speaker, WordCallback
from .factory import create_speaker

__all__ = ["Speaker", "WordCallback", "create_speaker"]
