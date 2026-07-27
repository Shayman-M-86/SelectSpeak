from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_name: str = "SelectSpeak"
    default_hotkey: str = "alt+s"
    preferred_voice_match: str = "natural"
    speech_rate: int = 0
    speech_volume: int = 100
    minimum_text_length: int = 3
    clipboard_wait_seconds: float = 2.0
    clipboard_poll_seconds: float = 0.05
    hotkey_debounce_seconds: float = 0.3
    capture_timeout_seconds: float = 15.0


DEFAULT_CONFIG = AppConfig()
