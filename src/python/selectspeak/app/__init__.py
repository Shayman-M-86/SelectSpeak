"""Application lifecycle and orchestration."""

from .application import SelectSpeakApp, main
from .startup import run_application

__all__ = ["SelectSpeakApp", "main", "run_application"]
