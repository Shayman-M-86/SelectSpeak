from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRECTORY_NAME = "SelectSpeak"


def is_frozen() -> bool:
    """Return whether SelectSpeak is running from a frozen executable."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Return the read-only application directory."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def native_dir() -> Path:
    """Return the directory containing the unified native runtime."""
    if is_frozen():
        return app_dir() / "native"
    return app_dir() / ".runtime" / "native"


def user_data_dir() -> Path:
    """Return the persistent, user-writable application directory."""
    override = os.environ.get("SELECTSPEAK_USER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DIRECTORY_NAME
    return Path.home() / "AppData" / "Local" / APP_DIRECTORY_NAME


def log_dir() -> Path:
    """Return the persistent diagnostic log directory."""
    return user_data_dir() / "logs"


def model_dir(model_name: str = "supertonic3") -> Path:
    """Return the persistent directory for a downloaded model."""
    return user_data_dir() / "models" / model_name


def settings_path() -> Path:
    """Return the versioned user settings file path."""
    return user_data_dir() / "settings.json"


def licenses_dir() -> Path:
    """Return the licenses shipped beside the frozen application."""
    return app_dir() / "licenses"
