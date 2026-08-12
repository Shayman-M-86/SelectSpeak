import logging

from ..config import AppConfig
from ..logging_setup import log_event, log_exception
from .contracts import Speaker, WordCallback
from .debug import SpeechDebugCallback

logger = logging.getLogger(__name__)


def create_speaker(
    config: AppConfig,
    word_callback: WordCallback | None = None,
    debug_callback: SpeechDebugCallback | None = None,
) -> Speaker:
    """Create the configured local speech backend."""
    backend = config.speech_backend.casefold()
    if backend not in {"auto", "natural", "sapi", "supertonic"}:
        raise ValueError(f"Unknown speech backend: {config.speech_backend}")
    if backend == "supertonic":
        from .backends.supertonic import SupertonicSpeaker

        speaker = SupertonicSpeaker(config.speech, word_callback, debug_callback)
        log_event(logger, logging.INFO, "speaker.backend.selected", backend=backend)
        return speaker
    if backend != "sapi":
        try:
            from .backends.natural import NaturalVoiceSpeaker

            speaker = NaturalVoiceSpeaker(config.speech, word_callback, debug_callback)
            log_event(
                logger, logging.INFO, "speaker.backend.selected", backend="natural"
            )
            return speaker
        except Exception:
            if backend == "natural":
                raise
            log_exception(logger, "speaker.natural_voice.unavailable")
    from .backends.sapi import SapiSpeaker

    log_event(logger, logging.INFO, "speaker.backend.selected", backend="sapi")
    return SapiSpeaker(config.speech, word_callback)
