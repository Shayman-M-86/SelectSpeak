from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import SpeechConfig
from .backends.natural import NaturalVoice
from .natural_identity import natural_voice_key
from .supertonic_setup import available_voices as available_supertonic_voices


@dataclass(frozen=True, slots=True)
class VoiceOption:
    key: str
    label: str
    short_label: str
    backend: str
    group: str
    package_path: str = ""
    sdk_voice_name: str = ""
    supertonic_voice: str = ""


def supertonic_voice_key(voice: str) -> str:
    return f"supertonic:{voice.casefold()}"


def build_voice_options(
    voices: list[NaturalVoice] | tuple[NaturalVoice, ...],
    config: SpeechConfig,
    *,
    supertonic_voices: tuple[str, ...] | None = None,
) -> tuple[VoiceOption, ...]:
    styles = supertonic_voices or available_supertonic_voices()
    options = [
        VoiceOption(
            key=supertonic_voice_key(style),
            label=f"Supertonic {style}",
            short_label=f"Supertonic {style}",
            backend="supertonic",
            group="Local neural voice",
            supertonic_voice=style,
        )
        for style in styles
    ]
    ordered_voices = sorted(
        voices,
        key=lambda voice: (
            _natural_voice_label(voice).casefold(),
            voice.package_path.casefold(),
            voice.name.casefold(),
        ),
    )
    for voice in ordered_voices:
        label = _natural_voice_label(voice)
        options.append(
            VoiceOption(
                key=natural_voice_key(voice.package_path, voice.name),
                label=label,
                short_label=_natural_voice_short_label(voice),
                backend="natural",
                group="Windows Natural Voices",
                package_path=voice.package_path,
                sdk_voice_name=voice.name,
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
