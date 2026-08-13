from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import SpeechConfig
from .backends.natural import NaturalVoice


@dataclass(frozen=True, slots=True)
class VoiceOption:
    key: str
    label: str
    short_label: str
    backend: str
    group: str
    package_path: str = ""


def natural_voice_key(package_path: str) -> str:
    return f"natural:{package_path.casefold()}"


def build_voice_options(
    voices: list[NaturalVoice] | tuple[NaturalVoice, ...],
    config: SpeechConfig,
) -> tuple[VoiceOption, ...]:
    options = [
        VoiceOption(
            key="supertonic",
            label=f"Supertonic {config.supertonic_voice}",
            short_label=f"Supertonic {config.supertonic_voice}",
            backend="supertonic",
            group="Local neural voice",
        )
    ]
    ordered_voices = sorted(
        voices,
        key=lambda voice: (
            voice.source != "installed",
            _natural_voice_label(voice).casefold(),
            voice.package_path.casefold(),
        ),
    )
    duplicate_names = {
        name
        for name in {_natural_voice_label(voice) for voice in ordered_voices}
        if sum(_natural_voice_label(item) == name for item in ordered_voices) > 1
    }
    for voice in ordered_voices:
        label = _natural_voice_label(voice)
        if label in duplicate_names:
            source = "installed" if voice.source == "installed" else "pinned fallback"
            label = f"{label} ({source})"
        options.append(
            VoiceOption(
                key=natural_voice_key(voice.package_path),
                label=label,
                short_label=_natural_voice_short_label(voice),
                backend="natural",
                group="Windows Natural Voices",
                package_path=voice.package_path,
            )
        )
    options.append(
        VoiceOption(
            key="sapi",
            label="Windows default voice (SAPI)",
            short_label="Windows SAPI",
            backend="sapi",
            group="System fallback",
        )
    )
    return tuple(options)


def _natural_voice_label(voice: NaturalVoice) -> str:
    return voice.display_name or voice.name or voice.package_path


def _natural_voice_short_label(voice: NaturalVoice) -> str:
    label = _natural_voice_label(voice)
    label = re.sub(r"^Microsoft\s+", "", label, flags=re.IGNORECASE)
    label = label.split(" - ", maxsplit=1)[0]
    label = label.replace("(Natural HD)", "HD").replace("(Natural)", "")
    return " ".join(label.split())
