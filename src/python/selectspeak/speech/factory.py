import logging

from ..config import AppConfig
from .backends.natural import NaturalVoiceSpeaker
from .backends.supertonic import SupertonicSpeaker
from .contracts import Speaker
from .debug import SpeechDebugCallback
from .supertonic_setup import SupertonicDependenciesMissing, activate_dependencies

logger = logging.getLogger(__name__)


def create_speaker(
    config: AppConfig,
    debug_callback: SpeechDebugCallback | None = None,
) -> Speaker:
    """Create the configured local speech backend."""
    backend = config.speech_backend.casefold()
    if backend not in {"auto", "natural", "supertonic"}:
        raise ValueError(f"Unknown speech backend: {config.speech_backend}")
    if backend == "supertonic":
        try:
            activate_dependencies()
        except SupertonicDependenciesMissing:
            logger.warning("speaker.supertonic.dependencies_missing; falling back to Natural Voice")
        else:
            speaker = SupertonicSpeaker(config.speech, debug_callback)
            logger.info("speaker.backend.selected backend=%s", backend)
            return speaker
    speaker = NaturalVoiceSpeaker(config.speech, debug_callback)
    logger.info("speaker.backend.selected backend=%s", "natural")
    return speaker
