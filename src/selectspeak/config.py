from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InputConfig:
    default_hotkey: str
    ocr_hotkey: str
    ocr_trigger_hotkey: str
    native_input_dll: str
    hotkey_debounce_seconds: float
    capture_timeout_seconds: float
    ocr_capture_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class SpeechConfig:
    preferred_voice_match: str
    speech_backend: str
    natural_voice_dll: str
    natural_voice_path: str
    natural_voice_credential: str
    supertonic_voice: str
    supertonic_language: str
    supertonic_steps: int
    supertonic_speed: float
    speech_rate: int
    speech_volume: int
    structure_pause_seconds: float
    minimum_text_length: int


@dataclass(frozen=True, slots=True)
class UiConfig:
    app_name: str
    auto_hide: bool
    speech_debug_enabled: bool


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    logging_enabled: bool
    log_file: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_name: str = "SelectSpeak"
    default_hotkey: str = "alt+s"
    ocr_hotkey: str = "alt+d"
    ocr_trigger_hotkey: str = "windows+shift+t"
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
    ocr_capture_timeout_seconds: float = 30.0

    @property
    def input(self) -> InputConfig:
        return InputConfig(
            self.default_hotkey,
            self.ocr_hotkey,
            self.ocr_trigger_hotkey,
            self.native_input_dll,
            self.hotkey_debounce_seconds,
            self.capture_timeout_seconds,
            self.ocr_capture_timeout_seconds,
        )

    @property
    def speech(self) -> SpeechConfig:
        return SpeechConfig(
            self.preferred_voice_match,
            self.speech_backend,
            self.natural_voice_dll,
            self.natural_voice_path,
            self.natural_voice_credential,
            self.supertonic_voice,
            self.supertonic_language,
            self.supertonic_steps,
            self.supertonic_speed,
            self.speech_rate,
            self.speech_volume,
            self.structure_pause_seconds,
            self.minimum_text_length,
        )

    @property
    def ui(self) -> UiConfig:
        return UiConfig(self.app_name, self.auto_hide, self.speech_debug_enabled)

    @property
    def logging(self) -> LoggingConfig:
        return LoggingConfig(self.logging_enabled, self.log_file)


DEFAULT_CONFIG = AppConfig()
