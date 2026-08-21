import logging

from ..config import AppConfig
from .contracts import Speaker
from .debug import SpeechDebugCallback

logger = logging.getLogger(__name__)


def create_speaker(
    config: AppConfig,
    debug_callback: SpeechDebugCallback | None = None,
) -> Speaker:
    """Create the configured local speech backend."""
    backend = config.speech_backend.casefold()
    if backend not in {"auto", "natural", "sapi", "supertonic"}:
        raise ValueError(f"Unknown speech backend: {config.speech_backend}")
    if backend == "supertonic":
        from .optional_dependencies import (
            SupertonicDependenciesMissing,
            activate_supertonic_dependencies,
        )

        try:
            activate_supertonic_dependencies()
        except SupertonicDependenciesMissing:
            logger.warning("speaker.supertonic.dependencies_missing; falling back to Windows speech")
            backend = "auto"
        else:
            from .backends.supertonic import SupertonicSpeaker

            speaker = SupertonicSpeaker(config.speech, debug_callback)
            logger.info("speaker.backend.selected backend=%s", backend)
            return speaker
    if backend != "sapi":
        try:
            from .backends.natural import NaturalVoiceSpeaker

            speaker = NaturalVoiceSpeaker(config.speech, debug_callback)
            logger.info("speaker.backend.selected backend=%s", "natural")
            return speaker
        except Exception:
            if backend == "natural":
                raise
            logger.exception("speaker.natural_voice.unavailable")
    from .backends.sapi import SapiSpeaker

    logger.info("speaker.backend.selected backend=%s", "sapi")
    return SapiSpeaker(config.speech)
