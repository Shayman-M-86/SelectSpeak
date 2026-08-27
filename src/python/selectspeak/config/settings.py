from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import DEFAULT_CONFIG, AppConfig
from .paths import settings_path

SETTINGS_SCHEMA_VERSION = 1


class SettingsError(RuntimeError):
    pass


class SettingsStore:
    """Load and atomically persist the user-editable application settings."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_path()
        self._lock = threading.Lock()

    def load(self, defaults: AppConfig = DEFAULT_CONFIG) -> AppConfig:
        if not self.path.is_file():
            return defaults
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SettingsError(f"Could not read settings from {self.path}: {error}") from error
        if not isinstance(payload, dict):
            raise SettingsError(f"Settings must contain a JSON object: {self.path}")
        if payload.get("schema_version") != SETTINGS_SCHEMA_VERSION:
            raise SettingsError(
                f"Unsupported settings schema {payload.get('schema_version')!r} in {self.path}"
            )
        return _apply_settings(defaults, payload)

    def save(self, config: AppConfig) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.{os.getpid()}.tmp")
            try:
                temporary.write_text(
                    json.dumps(_settings_payload(config), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, self.path)
            except OSError as error:
                temporary.unlink(missing_ok=True)
                raise SettingsError(f"Could not save settings to {self.path}: {error}") from error


def _settings_payload(config: AppConfig) -> dict[str, Any]:
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "speech_backend": config.speech_backend,
        "preferred_voice": config.preferred_voice_match,
        "hotkeys": {"speak": config.default_hotkey, "ocr": config.ocr_hotkey},
        "speech": {"rate": config.speech_rate, "volume": config.speech_volume},
        "supertonic": {
            "voice": config.supertonic_voice,
            "language": config.supertonic_language,
            "steps": config.supertonic_steps,
            "speed": config.supertonic_speed,
        },
        "ocr_language": config.ocr_language,
        "ui": {
            "auto_hide": config.auto_hide,
            "speech_debug_enabled": config.speech_debug_enabled,
            "clipboard_mode": config.clipboard_mode,
        },
        "logging": {
            "enabled": config.logging_enabled,
            "file": config.log_file,
        },
    }


def _apply_settings(defaults: AppConfig, payload: dict[str, Any]) -> AppConfig:
    hotkeys = _mapping(payload.get("hotkeys"))
    speech = _mapping(payload.get("speech"))
    supertonic = _mapping(payload.get("supertonic"))
    ui = _mapping(payload.get("ui"))
    logging = _mapping(payload.get("logging"))
    backend = _choice(payload.get("speech_backend"), {"auto", "natural", "supertonic"})
    # SAPI was retired in favor of Windows Natural Voice. Preserve speech for
    # existing settings instead of treating a former explicit choice as corrupt.
    if isinstance(payload.get("speech_backend"), str) and payload["speech_backend"].casefold() == "sapi":
        backend = "natural"
    return replace(
        defaults,
        speech_backend=backend or defaults.speech_backend,
        preferred_voice_match=_text(payload.get("preferred_voice"), defaults.preferred_voice_match),
        default_hotkey=_text(hotkeys.get("speak"), defaults.default_hotkey),
        ocr_hotkey=_text(hotkeys.get("ocr"), defaults.ocr_hotkey),
        speech_rate=_integer(speech.get("rate"), defaults.speech_rate, -10, 10),
        speech_volume=_integer(speech.get("volume"), defaults.speech_volume, 0, 100),
        supertonic_voice=_text(supertonic.get("voice"), defaults.supertonic_voice),
        supertonic_language=_text(supertonic.get("language"), defaults.supertonic_language),
        supertonic_steps=_integer(supertonic.get("steps"), defaults.supertonic_steps, 1, 100),
        supertonic_speed=_number(supertonic.get("speed"), defaults.supertonic_speed, 0.7, 2.0),
        ocr_language=_text(payload.get("ocr_language"), defaults.ocr_language, allow_empty=True),
        auto_hide=_boolean(ui.get("auto_hide"), defaults.auto_hide),
        speech_debug_enabled=_boolean(ui.get("speech_debug_enabled"), defaults.speech_debug_enabled),
        clipboard_mode=_boolean(ui.get("clipboard_mode"), defaults.clipboard_mode),
        logging_enabled=_boolean(logging.get("enabled"), defaults.logging_enabled),
        log_file=_text(logging.get("file"), defaults.log_file, allow_empty=True),
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any, default: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        return default
    stripped = value.strip()
    return stripped if stripped or allow_empty else default


def _boolean(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _integer(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if minimum <= value <= maximum else default


def _number(value: Any, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    return number if minimum <= number <= maximum else default


def _choice(value: Any, choices: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.casefold()
    return normalized if normalized in choices else None
