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
            _natural_voice_label(voice).casefold(),
            voice.package_path.casefold(),
        ),
    )
    for voice in ordered_voices:
        label = _natural_voice_label(voice)
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
