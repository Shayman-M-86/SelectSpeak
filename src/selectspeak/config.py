from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_name: str = "SelectSpeak"
    default_hotkey: str = "alt+s"
    preferred_voice_match: str = "natural"
    speech_backend: str = "auto"
    native_input_dll: str = ""
    natural_voice_dll: str = ""
    natural_voice_path: str = ""
    natural_voice_credential: str = ""
    supertonic_voice: str = "F4"
    supertonic_language: str = "en"
    supertonic_steps: int = 8
    supertonic_speed: float = 1.05
    auto_hide: bool = True
    speech_rate: int = 0
    speech_volume: int = 100
    structure_pause_seconds: float = 0.1
    speech_debug_enabled: bool = True
    logging_enabled: bool = True
    log_file: str = "selectspeak.log"
    minimum_text_length: int = 3
    hotkey_debounce_seconds: float = 0.3
    capture_timeout_seconds: float = 15.0


DEFAULT_CONFIG = AppConfig()
