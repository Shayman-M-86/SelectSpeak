from selectspeak.config import AppConfig
from selectspeak.speech.backends.natural import NaturalVoice
from selectspeak.speech.voices import build_voice_options, natural_voice_key


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


def test_duplicate_installed_and_pinned_voice_labels_explain_the_source() -> None:
    display_name = "Microsoft Aria (Natural) - English (United States)"
    options = build_voice_options(
        [
            NaturalVoice(
                "C:/WindowsApps/Aria",
                display_name,
                "en-US",
                display_name,
            ),
            NaturalVoice(
                "C:/SelectSpeak/Aria",
                display_name,
                "en-US",
                display_name,
                "pinned",
            ),
        ],
        AppConfig().speech,
    )

    natural_labels = [
        option.label for option in options if option.backend == "natural"
    ]
    assert natural_labels == [
        f"{display_name} (installed)",
        f"{display_name} (pinned fallback)",
    ]
