import json
from pathlib import Path

import pytest

from selectspeak.config import AppConfig
from selectspeak.config.settings import SETTINGS_SCHEMA_VERSION, SettingsError, SettingsStore


def test_settings_round_trip_every_persistent_category(tmp_path: Path) -> None:
    path = tmp_path / "SelectSpeak" / "settings.json"
    expected = AppConfig(
        speech_backend="natural",
        preferred_voice_match="C:/WindowsApps/Ava",
        default_hotkey="ctrl+f9",
        ocr_hotkey="alt+f10",
        speech_rate=2,
        speech_volume=72,
        supertonic_voice="M2",
        supertonic_language="en",
        supertonic_steps=12,
        supertonic_speed=1.2,
        ocr_language="en-AU",
        auto_hide=False,
        speech_debug_enabled=False,
        clipboard_mode=True,
        logging_enabled=True,
        log_file="C:/Temp/selectspeak-debug.log",
    )
    store = SettingsStore(path)

    store.save(expected)

    assert store.load() == expected
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SETTINGS_SCHEMA_VERSION
    assert not list(path.parent.glob("*.tmp"))


def test_settings_ignore_invalid_values_individually(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SETTINGS_SCHEMA_VERSION,
                "speech_backend": "unknown",
                "hotkeys": {"speak": 42, "ocr": "ctrl+f8"},
                "speech": {"rate": 99, "volume": 55},
                "supertonic": {"steps": 0, "speed": 1.3},
                "ui": {"auto_hide": "yes", "clipboard_mode": True},
            }
        ),
        encoding="utf-8",
    )

    config = SettingsStore(path).load()

    assert config.speech_backend == "auto"
    assert config.default_hotkey == "alt+s"
    assert config.ocr_hotkey == "ctrl+f8"
    assert config.speech_rate == 0
    assert config.speech_volume == 55
    assert config.supertonic_steps == 8
    assert config.supertonic_speed == 1.3
    assert config.auto_hide
    assert config.clipboard_mode


def test_settings_reject_an_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version": 99}', encoding="utf-8")

    with pytest.raises(SettingsError, match="Unsupported settings schema"):
        SettingsStore(path).load()
