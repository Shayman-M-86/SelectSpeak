import logging

from ..config import AppConfig
from .backends.natural import NaturalVoiceSpeaker
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
            # Imported here rather than at module scope: the backend needs
            # numpy and supertonic, which only become importable once
            # activate_dependencies() has put the installed dependency layer
            # on sys.path. A top-level import would fail at startup instead.
            from .backends.supertonic import SupertonicSpeaker

            speaker = SupertonicSpeaker(config.speech, debug_callback)
            logger.info("speaker.backend.selected backend=%s", backend)
            return speaker
    speaker = NaturalVoiceSpeaker(config.speech, debug_callback)
    logger.info("speaker.backend.selected backend=%s", "natural")
    return speaker
