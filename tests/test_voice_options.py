from selectspeak.config import AppConfig
from selectspeak.speech.backends.natural import NaturalVoice
from selectspeak.speech.voices import build_voice_options, natural_voice_key
from selectspeak.ui.player import PlayerWindow


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
    player._backend_button = Button()

    player._show_voice_menu()

    assert events == ["refresh", "popup", "release"]


def test_installing_supertonic_is_visible_and_disables_speech_controls() -> None:
    class Value:
        selected = ""

        @classmethod
        def set(cls, value: str) -> None:
            cls.selected = value

    class Widget:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        def config(self, **values: str) -> None:
            self.values.update(values)

    player = object.__new__(PlayerWindow)
    player._selected_voice_key = Value()
    player._backend_button = Widget()
    player._read_button = Widget()
    player._play_button = Widget()
    player._reader_text = ""
    player._resize = lambda _height: None

    player.set_voice_selection("supertonic", "Supertonic F4", activity="installing")

    assert Value.selected == "supertonic"
    assert player._backend_button.values["text"] == "Voice: Installing Supertonic…"
    assert player._backend_button.values["state"] == "disabled"
    assert player._read_button.values["state"] == "disabled"
    assert player._play_button.values["state"] == "disabled"


def test_ready_supertonic_reenables_reading_and_reports_ready() -> None:
    class Widget:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        def config(self, **values: str) -> None:
            self.values.update(values)

    player = object.__new__(PlayerWindow)
    player._status = Widget()
    player.show = lambda: None

    player.show_backend_ready("Supertonic F4")

    assert player._status.values["text"] == "✓  Supertonic F4 is ready"
