from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_name: str = "SelectSpeak"
    default_hotkey: str = "alt+s"
    preferred_voice_match: str = "natural"
    speech_rate: int = 0
    speech_volume: int = 100
    structure_pause_seconds: float = 0.1
    logging_enabled: bool = False
    log_file: str = "selectspeak.log"
    minimum_text_length: int = 3
    hotkey_debounce_seconds: float = 0.3
    capture_timeout_seconds: float = 15.0


DEFAULT_CONFIG = AppConfig()
