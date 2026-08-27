from selectspeak.config import AppConfig
from selectspeak.speech.backends.natural import NaturalVoice
from selectspeak.speech.natural_identity import parse_natural_voice_key
from selectspeak.speech.voices import build_voice_options, natural_voice_key, supertonic_voice_key


def test_voice_options_include_every_installed_supertonic_style_and_natural_voice() -> None:
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

    options = build_voice_options(voices, AppConfig().speech, supertonic_voices=("F2", "M3"))

    assert [(option.backend, option.short_label) for option in options] == [
        ("supertonic", "Supertonic F2"),
        ("supertonic", "Supertonic M3"),
        ("natural", "Aria"),
        ("natural", "Ava HD"),
    ]
    assert options[0].key == supertonic_voice_key("F2")
    assert options[0].supertonic_voice == "F2"
    assert options[2].key == natural_voice_key(
        "C:/WindowsApps/Aria", "Microsoft Aria (Natural) - English (United States)"
    )
    assert options[2].package_path == "C:/WindowsApps/Aria"
    assert options[2].sdk_voice_name == "Microsoft Aria (Natural) - English (United States)"


def test_natural_voice_option_key_distinguishes_sdk_voices_in_one_package() -> None:
    package = "C:/WindowsApps/Shared"
    voices = [
        NaturalVoice(package, "SDK Alpha", "en-US", "Alpha"),
        NaturalVoice(package, "SDK Beta", "en-US", "Beta"),
    ]

    options = build_voice_options(voices, AppConfig().speech, supertonic_voices=("F4",))

    assert options[1].key != options[2].key
    assert parse_natural_voice_key(options[1].key) == (package, "SDK Alpha")
    assert parse_natural_voice_key(options[2].key) == (package, "SDK Beta")
