from __future__ import annotations

import ctypes
import logging
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ...config import SpeechConfig
from ...logging_setup import log_event, log_exception, text_preview
from ...native import get_native_bridge
from ...runtime_paths import repository_runtime_path
from ..debug import SpeechDebugCallback, SpeechDebugEvent
from ..pipeline import AdaptiveSpeechPipeline, GenerationStatistics
from ..playback import PlaybackController, SpeechRequest
from ..waveout import WaveOutPlayer

SAMPLE_RATE = 24_000

logger = logging.getLogger(__name__)

AudioCallback = Callable[[bytes], None]
BoundaryCallback = Callable[[int, int, int], None]


class NaturalVoiceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NaturalVoice:
    package_path: str
    name: str
    locale: str
    display_name: str
    source: str = "installed"


_AUDIO_CALLBACK = ctypes.CFUNCTYPE(
    None, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32, ctypes.c_void_p
)
_WORD_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_uint64,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_void_p,
)
_VOICE_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_wchar_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
)


def _decode(value: bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if value else ""


def find_pinned_natural_voices(root: Path | None = None) -> list[NaturalVoice]:
    """Find extracted, app-owned voice packages that Windows cannot update."""
    voice_roots = (
        (root,)
        if root is not None
        else (
            repository_runtime_path("native", "voices"),
            repository_runtime_path("natural_voice", "voices"),
        )
    )
    packages_by_identity: dict[str, Path] = {}
    for voice_root in voice_roots:
        if not voice_root.is_dir():
            continue
        for token_path in voice_root.rglob("Tokens.xml"):
            package_path = token_path.parent
            packages_by_identity.setdefault(package_path.name.casefold(), package_path)
    package_paths = sorted(
        packages_by_identity.values(),
        key=lambda path: str(path).casefold(),
    )
    return [_pinned_voice(path) for path in package_paths]


def discover_natural_voices(config: SpeechConfig) -> list[NaturalVoice]:
    """List selectable installed and pinned voices without synthesizing."""
    if config.natural_voice_path:
        package_path = Path(config.natural_voice_path).resolve()
        return [
            NaturalVoice(
                str(package_path),
                package_path.name,
                "",
                package_path.name,
                "configured",
            )
        ]

    dll = get_native_bridge(config.native_dll).library
    voices: list[NaturalVoice] = []

    @_VOICE_CALLBACK
    def collect_voice(
        package_path: str,
        name: bytes,
        locale: bytes,
        display_name: bytes,
        _context: int,
    ) -> None:
        voices.append(
            NaturalVoice(
                package_path,
                _decode(name),
                _decode(locale),
                _decode(display_name),
            )
        )

    dll.ss_voice_list.argtypes = [_VOICE_CALLBACK, ctypes.c_void_p]
    dll.ss_voice_list.restype = ctypes.c_uint32
    dll.ss_voice_list(collect_voice, None)
    return [*voices, *find_pinned_natural_voices()]


def _pinned_voice(package_path: Path) -> NaturalVoice:
    name = package_path.name
    locale = ""
    try:
        token = ET.parse(package_path / "Tokens.xml").find(".//Token")
        if token is not None:
            display = token.find("./String[@name='']")
            name_attribute = token.find("./Attribute[@name='Name']")
            if display is not None and display.get("value"):
                name = display.get("value", name)
            elif name_attribute is not None and name_attribute.get("value"):
                name = name_attribute.get("value", name)
    except (ET.ParseError, OSError):
        pass
    return NaturalVoice(
        package_path=str(package_path.resolve()),
        name=name,
        locale=locale,
        display_name=name,
        source="pinned",
    )


class NaturalVoiceEngine:
    """Thin ctypes owner for the process-wide native Natural Voice engine."""

    def __init__(
        self,
        config: SpeechConfig,
        audio_callback: AudioCallback,
        boundary_callback: BoundaryCallback,
    ) -> None:
        self._bridge = get_native_bridge(config.native_dll)
        self._dll = self._bridge.library
        self._configure_api()
        self._audio_callback = _AUDIO_CALLBACK(self._on_audio)
        self._word_callback = _WORD_CALLBACK(self._on_word)
        self._voice_callback = _VOICE_CALLBACK(self._on_voice)
        self._audio_consumer = audio_callback
        self._boundary_consumer = boundary_callback
        self._voices: list[NaturalVoice] = []

        self._dll.ss_voice_set_audio_callback(self._audio_callback, None)
        self._dll.ss_voice_set_word_callback(self._word_callback, None)
        self._credential = (
            config.natural_voice_credential.encode("utf-8")
            if config.natural_voice_credential
            else None
        )
        failures: list[str] = []
        if config.natural_voice_path:
            package_path = str(Path(config.natural_voice_path).resolve())
            candidates = [
                NaturalVoice(
                    package_path=package_path,
                    name=Path(package_path).name,
                    locale="",
                    display_name="",
                    source="configured",
                )
            ]
            self._available_voices = tuple(candidates)
            if self._initialize_first(candidates, self._credential, failures):
                return
            raise NaturalVoiceError(
                "The configured Natural Voice package could not be initialized. "
                + " | ".join(failures)
            )

        pinned = find_pinned_natural_voices()
        installed = self._enumerate_installed_voices()
        candidates = self._ordered_voices(
            [*installed, *pinned],
            config.preferred_voice_match,
        )
        self._available_voices = tuple(candidates)
        if self._initialize_first(candidates, self._credential, failures):
            return
        if not pinned and not installed:
            raise NaturalVoiceError(
                self._last_error()
                or "No pinned or installed Windows Natural Voices were found"
            )
        raise NaturalVoiceError(
            "No compatible installed or pinned Natural Voice could be initialized. "
            + " | ".join(failures)
        )

    @property
    def available_voices(self) -> tuple[NaturalVoice, ...]:
        return self._available_voices

    def refresh_voices(self) -> tuple[NaturalVoice, ...]:
        """Refresh installed and pinned packages without recreating the engine."""
        voices = [
            *self._enumerate_installed_voices(),
            *find_pinned_natural_voices(),
        ]
        active_voice = getattr(self, "voice", None)
        if active_voice is not None and not any(
            voice.package_path.casefold() == active_voice.package_path.casefold()
            for voice in voices
        ):
            voices.append(active_voice)
        self._available_voices = tuple(voices)
        return self._available_voices

    def select_voice(self, package_path: str) -> NaturalVoice:
        self.refresh_voices()
        selected = next(
            (
                voice
                for voice in self._available_voices
                if voice.package_path.casefold() == package_path.casefold()
            ),
            None,
        )
        if selected is None:
            raise NaturalVoiceError(
                f"Natural Voice is no longer available: {package_path}"
            )
        previous = self.voice
        failures: list[str] = []
        if self._initialize_first([selected], self._credential, failures):
            return selected

        rollback_failures: list[str] = []
        self._initialize_first([previous], self._credential, rollback_failures)
        raise NaturalVoiceError(
            "The selected Natural Voice could not be initialized. "
            + " | ".join(failures)
        )

    def _enumerate_installed_voices(self) -> list[NaturalVoice]:
        self._voices.clear()
        self._dll.ss_voice_list(self._voice_callback, None)
        return list(self._voices)

    def _initialize_first(
        self,
        candidates: list[NaturalVoice],
        credential: bytes | None,
        failures: list[str],
    ) -> bool:
        for candidate in candidates:
            log_event(
                logger,
                logging.INFO,
                "natural_voice.probing",
                voice=candidate.name,
                locale=candidate.locale,
                package_path=candidate.package_path,
                source=candidate.source,
            )
            if not self._dll.ss_voice_initialize(candidate.package_path, credential):
                self.voice = candidate
                log_event(
                    logger,
                    logging.INFO,
                    "natural_voice.selected",
                    voice=candidate.name,
                    locale=candidate.locale,
                    package_path=candidate.package_path,
                    source=candidate.source,
                    available_voice_count=len(candidates),
                )
                return True
            failures.append(f"{candidate.name}: {self._last_error()}")
        return False

    def speak(self, text: str) -> None:
        if self._dll.ss_voice_speak(text):
            raise NaturalVoiceError(self._last_error())

    def stop(self) -> None:
        if self._dll.ss_voice_stop():
            raise NaturalVoiceError(self._last_error())

    def close(self) -> None:
        self._dll.ss_voice_shutdown()

    def _configure_api(self) -> None:
        self._dll.ss_voice_list.argtypes = [_VOICE_CALLBACK, ctypes.c_void_p]
        self._dll.ss_voice_list.restype = ctypes.c_uint32
        self._dll.ss_voice_initialize.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_char_p,
        ]
        self._dll.ss_voice_initialize.restype = ctypes.c_int
        self._dll.ss_voice_set_audio_callback.argtypes = [
            _AUDIO_CALLBACK,
            ctypes.c_void_p,
        ]
        self._dll.ss_voice_set_word_callback.argtypes = [
            _WORD_CALLBACK,
            ctypes.c_void_p,
        ]
        self._dll.ss_voice_speak.argtypes = [ctypes.c_wchar_p]
        self._dll.ss_voice_speak.restype = ctypes.c_int
        self._dll.ss_voice_stop.restype = ctypes.c_int
        self._dll.ss_voice_shutdown.restype = None
        self._dll.ss_voice_last_error.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        self._dll.ss_voice_last_error.restype = ctypes.c_uint32

    def _on_audio(
        self,
        data: Any,
        length: int,
        _context: int,
    ) -> None:
        self._audio_consumer(ctypes.string_at(data, length))

    def _on_word(
        self, audio_offset: int, text_offset: int, length: int, _context: int
    ) -> None:
        self._boundary_consumer(audio_offset, text_offset, length)

    def _on_voice(
        self,
        package_path: str,
        name: bytes,
        locale: bytes,
        display_name: bytes,
        _context: int,
    ) -> None:
        self._voices.append(
            NaturalVoice(
                package_path, _decode(name), _decode(locale), _decode(display_name)
            )
        )

    def _last_error(self) -> str:
        required = self._dll.ss_voice_last_error(None, 0)
        buffer = ctypes.create_string_buffer(max(required, 1))
        self._dll.ss_voice_last_error(buffer, len(buffer))
        return buffer.value.decode("utf-8", errors="replace")

    @staticmethod
    def _choose_voice(voices: list[NaturalVoice], preferred: str) -> NaturalVoice:
        return NaturalVoiceEngine._ordered_voices(voices, preferred)[0]

    @staticmethod
    def _ordered_voices(
        voices: list[NaturalVoice], preferred: str
    ) -> list[NaturalVoice]:
        needle = preferred.casefold().strip()
        if not needle:
            return list(voices)

        def matches(voice: NaturalVoice) -> bool:
            haystack = " ".join(
                (voice.name, voice.display_name, voice.locale, voice.package_path)
            ).casefold()
            return needle in haystack

        return [voice for voice in voices if matches(voice)] + [
            voice for voice in voices if not matches(voice)
        ]


_SpeechRequest = SpeechRequest


class _Engine(Protocol):
    @property
    def voice(self) -> NaturalVoice: ...

    @property
    def available_voices(self) -> tuple[NaturalVoice, ...]: ...

    def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
    def refresh_voices(self) -> tuple[NaturalVoice, ...]: ...
    def select_voice(self, package_path: str) -> NaturalVoice: ...


class NaturalVoiceSpeaker:
    """Match the app's speaker contract using the direct embedded engine."""

    def __init__(
        self,
        config: SpeechConfig,
        word_callback: Callable[[str, int, int], None] | None,
        debug_callback: SpeechDebugCallback | None = None,
    ) -> None:
        self._config = config
        self._word_callback = word_callback
        self._debug_callback = debug_callback
        self._playback = PlaybackController()
        self._request_text = ""
        self._segment_text_offset = 0
        self._segment_audio_base = 0
        self._generation_statistics = GenerationStatistics()
        self._player = WaveOutPlayer(
            self._on_played_word,
            config.speech_volume,
            debug_callback=debug_callback,
        )
        self._engine: _Engine = NaturalVoiceEngine(
            config, self._on_engine_audio, self._on_engine_boundary
        )
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="NaturalVoiceSpeaker"
        )
        self._thread.start()

    @property
    def active(self) -> bool:
        return self._playback.active

    @property
    def paused(self) -> bool:
        return self._playback.paused

    @property
    def voice(self) -> NaturalVoice:
        return self._engine.voice

    @property
    def available_voices(self) -> tuple[NaturalVoice, ...]:
        return self._engine.available_voices

    def refresh_voices(self) -> tuple[NaturalVoice, ...]:
        return self._engine.refresh_voices()

    def select_voice(self, package_path: str) -> NaturalVoice:
        self.stop()
        selected = self._engine.select_voice(package_path)
        log_event(
            logger,
            logging.INFO,
            "natural_voice.changed",
            voice=selected.name,
            package_path=selected.package_path,
            source=selected.source,
        )
        return selected

    def speak(self, text: str) -> int | None:
        if len(text) < self._config.minimum_text_length:
            return None
        try:
            request, active = self._playback.submit(text)
        except RuntimeError as error:
            raise NaturalVoiceError("The Natural Voice worker has failed") from error
        if active:
            self._player.stop()
            self._engine.stop()
        return request.generation

    def stop(self) -> None:
        _generation, active = self._playback.cancel()
        if active:
            self._player.stop()
            self._engine.stop()

    def pause(self) -> None:
        if self._playback.pause_now():
            self._player.pause()

    def resume(self) -> None:
        if self._playback.resume_now():
            self._player.resume()

    def wait_until_done(self, generation: int) -> bool:
        return self._playback.wait_until_done(generation)

    def _run(self) -> None:
        while True:
            request = self._playback.next_request()
            if not self._playback.is_current(request.generation):
                continue
            try:
                self._speak_request(request)
            except Exception:
                if self._is_superseded(request.generation):
                    continue
                log_exception(
                    logger,
                    "natural_voice.request.failed",
                    generation=request.generation,
                )
                self._playback.fail(request.generation)
                return

    def _speak_request(self, request: _SpeechRequest) -> None:
        if not self._playback.begin(request.generation):
            return
        player_started = False
        try:
            pipeline = AdaptiveSpeechPipeline(request.text, self._generation_statistics)
            decision = pipeline.choose_next()
            if decision is None:
                return
            self._request_text = request.text
            self._player.start()
            player_started = True
            index = 0
            while decision is not None:
                if not self._playback.is_current(request.generation):
                    return
                segment = decision.segment
                self._segment_text_offset = segment.offset
                self._segment_audio_base = self._player.fed_bytes
                started_at = time.monotonic()
                self._engine.speak(segment.text)
                synthesis_seconds = time.monotonic() - started_at
                generated_bytes = self._player.fed_bytes - self._segment_audio_base
                pipeline.record_generation(segment, synthesis_seconds)
                debug_event = SpeechDebugEvent(
                    kind="chunk_ready",
                    backend="natural",
                    chunk_index=index,
                    text_offset=segment.offset,
                    text_length=len(segment.text),
                    target_characters=decision.target_characters,
                    predicted_synthesis_ms=round(
                        decision.predicted_synthesis_seconds * 1000
                    ),
                    actual_synthesis_ms=round(synthesis_seconds * 1000),
                    audio_ms=round(generated_bytes / (SAMPLE_RATE * 2) * 1000),
                    runway_ms=round(decision.playback_runway * 1000),
                    boundary=_boundary_name(segment.pause_after),
                )
                debug_callback = getattr(self, "_debug_callback", None)
                if debug_callback:
                    debug_callback(debug_event)
                add_debug_marker = getattr(self._player, "add_debug_marker", None)
                if add_debug_marker:
                    add_debug_marker(self._segment_audio_base, debug_event)
                if not pipeline.remaining_characters:
                    break
                if segment.pause_after:
                    self._player.feed_silence(self._config.structure_pause_seconds)
                    log_event(
                        logger,
                        logging.DEBUG,
                        "speech.structure_pause.queued",
                        backend="natural",
                        configured_ms=round(
                            self._config.structure_pause_seconds * 1000
                        ),
                        segment_index=index,
                    )
                runway = self._player.buffered_seconds
                decision = pipeline.choose_next(runway)
                if decision is not None:
                    log_event(
                        logger,
                        logging.DEBUG,
                        "natural_voice.chunk.selected",
                        segment_index=index + 1,
                        target_characters=decision.target_characters,
                        actual_characters=len(decision.segment.text),
                        playback_runway=round(runway, 3),
                        observations=pipeline.statistics.observations,
                        text_preview=text_preview(decision.segment.text),
                    )
                index += 1
        finally:
            if player_started:
                self._player.finish()
            self._playback.complete(request.generation)

    def _on_engine_audio(self, data: bytes) -> None:
        self._player.feed(data)

    def _on_engine_boundary(
        self, audio_offset: int, text_offset: int, length: int
    ) -> None:
        self._player.add_boundary(
            audio_offset,
            self._segment_text_offset + text_offset,
            length,
            base_byte_offset=self._segment_audio_base,
        )

    def _on_played_word(self, position: int, length: int) -> None:
        if self._word_callback:
            self._word_callback(self._request_text, position, length)

    def _is_superseded(self, generation: int) -> bool:
        return not self._playback.is_current(generation)


def _boundary_name(pause_after: bool) -> str:
    return "sentence/structure" if pause_after else "technical"
