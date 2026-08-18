from selectspeak.config import AppConfig
from selectspeak.speech.backends.natural import NaturalVoice
from selectspeak.speech.voices import build_voice_options, natural_voice_key
from selectspeak.ui import player as player_module
from selectspeak.ui.player import PlayerWindow
from selectspeak.ui.theme import ICON_ACCEPT, load_palette


class _FakeWidget:
    """Stand-in for the Fluent controls, the status labels and the reader Text.

    Records whatever the player sets so tests can assert on the outcome without
    a live Tk window.
    """

    def __init__(self, *, mapped: bool = True) -> None:
        self.values: dict[str, object] = {}
        self.enabled = True
        self._mapped = mapped

    def config(self, **values: object) -> None:
        self.values.update(values)

    def tag_config(self, *_args: str, **_values: object) -> None:
        pass

    def winfo_ismapped(self) -> bool:
        return self._mapped

    def pack(self, **_values: object) -> None:
        self._mapped = True

    def pack_forget(self) -> None:
        self._mapped = False

    def configure_state(self, *, enabled: bool) -> None:
        self.enabled = enabled

    def set_active(self, _active: bool, *, font: object) -> None:
        self.values["font"] = font

    def set_text(self, text: str) -> None:
        self.values["text"] = text

    def set_icon(self, icon: str) -> None:
        self.values["icon"] = icon

    def set_command(self, command: object) -> None:
        self.values["command"] = command


def test_voice_options_include_every_engine_and_natural_voice() -> None:
    voices = [
        NaturalVoice(
            "C:/WindowsApps/AvaHD",
            "Microsoft Ava (Natural HD) - English (United States)",
            "en-US",
            "Microsoft Ava (Natural HD) - English (United States)",
        ),
        NaturalVoice(
            "C:/WindowsApps/Aria",
            "Microsoft Aria (Natural) - English (United States)",
            "en-US",
            "Microsoft Aria (Natural) - English (United States)",
        ),
    ]

    options = build_voice_options(voices, AppConfig().speech)

    assert [(option.backend, option.short_label) for option in options] == [
        ("supertonic", "Supertonic F4"),
        ("natural", "Aria"),
        ("natural", "Ava HD"),
        ("sapi", "Windows SAPI"),
    ]
    assert options[1].key == natural_voice_key("C:/WindowsApps/Aria")
    assert options[1].package_path == "C:/WindowsApps/Aria"


def test_opening_voice_menu_refreshes_before_displaying_options() -> None:
    events: list[str] = []

    class Menu:
        def tk_popup(self, _x: int, _y: int) -> None:
            events.append("popup")

        def grab_release(self) -> None:
            events.append("release")

    class Button:
        @staticmethod
        def winfo_rootx() -> int:
            return 10

        @staticmethod
        def winfo_rooty() -> int:
            return 20

        @staticmethod
        def winfo_height() -> int:
            return 5

    player = object.__new__(PlayerWindow)
    player._on_refresh_voices = lambda: events.append("refresh")
    player._voice_options = (object(),)
    player._voice_menu = Menu()
    player._voice_button = Button()

    player._show_voice_menu()

    assert events == ["refresh", "popup", "release"]


def test_installing_supertonic_is_visible_and_disables_speech_controls() -> None:
    class Value:
        selected = ""

        @classmethod
        def set(cls, value: str) -> None:
            cls.selected = value

    player = object.__new__(PlayerWindow)
    player._selected_voice_key = Value()
    player._voice_button = _FakeWidget()
    player._read_button = _FakeWidget()
    player._play_button = _FakeWidget()
    player._reader_text = ""
    player._font_caption = ("Segoe UI Variable Text", 8)
    player._font_caption_strong = ("Segoe UI Variable Text", 8, "bold")
    player._resize = lambda _height: None

    player.set_voice_selection("supertonic", "Supertonic F4", activity="installing")

    assert Value.selected == "supertonic"
    assert player._voice_button.values["text"] == "Installing Supertonic…"
    assert not player._voice_button.enabled
    assert not player._read_button.enabled
    assert not player._play_button.enabled


def test_ready_supertonic_reenables_reading_and_reports_ready() -> None:
    player = object.__new__(PlayerWindow)
    player._status = _FakeWidget()
    player._status_icon = _FakeWidget()
    player._palette = load_palette()
    player.show = lambda: None

    player.show_backend_ready("Supertonic F4")

    assert player._status.values["text"] == "Supertonic F4 is ready"
    # The tick is an icon glyph beside the text, not part of the sentence.
    assert player._status_icon.values["text"] == ICON_ACCEPT


def test_player_shows_over_fullscreen_and_records_safe_hide_mode(monkeypatch) -> None:
    player = object.__new__(PlayerWindow)
    player._palette = load_palette()
    player._reader_text = ""
    player._reader_frame = type("Frame", (), {"winfo_ismapped": lambda self: False})()
    player._reader = _FakeWidget()
    player._play_button = _FakeWidget()
    player._stop_button = _FakeWidget()
    player._debug_enabled = False
    player._playback_started_fullscreen = False
    player._on_pause = lambda: None
    player._start_animation = lambda: None
    player._show_reader = lambda _text: None
    shown: list[bool] = []
    player.show = lambda: shown.append(True)
    monkeypatch.setattr(player_module, "foreground_window_is_fullscreen", lambda: True)

    player.set_playback(speaking=True, text="Fullscreen reading")

    assert shown == [True]
    assert player._playback_started_fullscreen


def test_fullscreen_auto_hide_uses_transparent_mapped_window() -> None:
    player = object.__new__(PlayerWindow)
    player._palette = load_palette()
    player._reader_text = "Spoken text"
    player._reader = _FakeWidget()
    player._play_button = _FakeWidget()
    player._stop_button = _FakeWidget()
    player._auto_hide = True
    player._playback_started_fullscreen = True
    player._on_play = lambda: None
    player._stop_animation = lambda: None
    player._hide_reader = lambda _hint: None
    scheduled: list[object] = []
    player.after_idle = lambda callback: scheduled.append(callback)

    player.set_playback(speaking=False, text="Spoken text")

    assert scheduled == [player._soft_hide]
    assert not player._playback_started_fullscreen
