from __future__ import annotations

import ctypes
import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Protocol

from .config import AppConfig
from .logging_setup import log_event
from .text_processing import strip_display_bullet_prefix

SAMPLE_RATE = 24_000
BYTES_PER_SAMPLE = 2
BYTES_PER_SECOND = SAMPLE_RATE * BYTES_PER_SAMPLE
PLAYBACK_BLOCK_BYTES = BYTES_PER_SECOND // 10
PREBUFFER_BYTES = PLAYBACK_BLOCK_BYTES * 2
MAX_QUEUED_BUFFERS = 4
WHDR_DONE = 0x00000001
TIME_MS = 0x0001
TIME_SAMPLES = 0x0002
TIME_BYTES = 0x0004

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


def find_natural_voice_dll(configured_path: str = "") -> Path:
    candidates = [
        configured_path,
        os.environ.get("SELECTSPEAK_NATURAL_VOICE_DLL", ""),
        str(
            Path(__file__).resolve().parents[2]
            / ".runtime"
            / "natural_voice"
            / "selectspeak_natural_voice.dll"
        ),
        str(Path(__file__).with_name("selectspeak_natural_voice.dll")),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise NaturalVoiceError(
        "Natural Voice bridge not found; build native/natural_voice or set "
        "SELECTSPEAK_NATURAL_VOICE_DLL"
    )


class NaturalVoiceEngine:
    """Thin ctypes owner for the process-wide native Natural Voice engine."""

    def __init__(
        self,
        config: AppConfig,
        audio_callback: AudioCallback,
        boundary_callback: BoundaryCallback,
    ) -> None:
        dll_path = find_natural_voice_dll(config.natural_voice_dll)
        if hasattr(os, "add_dll_directory"):
            self._dll_directory = os.add_dll_directory(str(dll_path.parent))
        self._dll = ctypes.CDLL(str(dll_path))
        self._configure_api()
        self._audio_callback = _AUDIO_CALLBACK(self._on_audio)
        self._word_callback = _WORD_CALLBACK(self._on_word)
        self._voice_callback = _VOICE_CALLBACK(self._on_voice)
        self._audio_consumer = audio_callback
        self._boundary_consumer = boundary_callback
        self._voices: list[NaturalVoice] = []

        self._dll.nv_set_audio_callback(self._audio_callback, None)
        self._dll.nv_set_word_callback(self._word_callback, None)
        if config.natural_voice_path:
            package_path = str(Path(config.natural_voice_path).resolve())
            voice = NaturalVoice(
                package_path=package_path,
                name=Path(package_path).name,
                locale="",
                display_name="",
            )
        else:
            self._dll.nv_list_voices(self._voice_callback, None)
            if not self._voices:
                raise NaturalVoiceError(
                    self._last_error()
                    or "No installed Windows Natural Voices were found"
                )
            voice = self._choose_voice(self._voices, config.preferred_voice_match)
        credential = (
            config.natural_voice_credential.encode("utf-8")
            if config.natural_voice_credential
            else None
        )
        candidates = (
            [voice]
            if config.natural_voice_path
            else self._ordered_voices(self._voices, config.preferred_voice_match)
        )
        failures: list[str] = []
        for candidate in candidates:
            log_event(
                logger,
                logging.INFO,
                "natural_voice.probing",
                voice=candidate.name,
                locale=candidate.locale,
                package_path=candidate.package_path,
            )
            if not self._dll.nv_initialize(candidate.package_path, credential):
                self.voice = candidate
                log_event(
                    logger,
                    logging.INFO,
                    "natural_voice.selected",
                    voice=candidate.name,
                    locale=candidate.locale,
                    package_path=candidate.package_path,
                    available_voice_count=len(candidates),
                )
                break
            failures.append(f"{candidate.name}: {self._last_error()}")
        else:
            raise NaturalVoiceError(
                "No compatible Natural Voice package could be initialized. "
                + " | ".join(failures)
            )

    def speak(self, text: str) -> None:
        if self._dll.nv_speak(text):
            raise NaturalVoiceError(self._last_error())

    def stop(self) -> None:
        if self._dll.nv_stop():
            raise NaturalVoiceError(self._last_error())

    def close(self) -> None:
        self._dll.nv_shutdown()
        directory = getattr(self, "_dll_directory", None)
        if directory is not None:
            directory.close()

    def _configure_api(self) -> None:
        self._dll.nv_list_voices.argtypes = [_VOICE_CALLBACK, ctypes.c_void_p]
        self._dll.nv_list_voices.restype = ctypes.c_uint32
        self._dll.nv_initialize.argtypes = [ctypes.c_wchar_p, ctypes.c_char_p]
        self._dll.nv_initialize.restype = ctypes.c_int
        self._dll.nv_set_audio_callback.argtypes = [_AUDIO_CALLBACK, ctypes.c_void_p]
        self._dll.nv_set_word_callback.argtypes = [_WORD_CALLBACK, ctypes.c_void_p]
        self._dll.nv_speak.argtypes = [ctypes.c_wchar_p]
        self._dll.nv_speak.restype = ctypes.c_int
        self._dll.nv_stop.restype = ctypes.c_int
        self._dll.nv_shutdown.restype = None
        self._dll.nv_last_error.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        self._dll.nv_last_error.restype = ctypes.c_uint32

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
        required = self._dll.nv_last_error(None, 0)
        buffer = ctypes.create_string_buffer(max(required, 1))
        self._dll.nv_last_error(buffer, len(buffer))
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


class _WaveHeader(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", ctypes.c_uint32),
        ("dwBytesRecorded", ctypes.c_uint32),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", ctypes.c_uint32),
        ("dwLoops", ctypes.c_uint32),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


class _WaveFormat(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.c_uint16),
        ("nChannels", ctypes.c_uint16),
        ("nSamplesPerSec", ctypes.c_uint32),
        ("nAvgBytesPerSec", ctypes.c_uint32),
        ("nBlockAlign", ctypes.c_uint16),
        ("wBitsPerSample", ctypes.c_uint16),
        ("cbSize", ctypes.c_uint16),
    ]


class _MMTimeValue(ctypes.Union):
    _fields_ = [
        ("ms", ctypes.c_uint32),
        ("sample", ctypes.c_uint32),
        ("cb", ctypes.c_uint32),
        ("ticks", ctypes.c_uint32),
        ("smpte", ctypes.c_uint8 * 8),
    ]


class _MMTime(ctypes.Structure):
    _fields_ = [("wType", ctypes.c_uint32), ("u", _MMTimeValue)]


class WaveOutPlayer:
    """Streams raw PCM with winmm and emits boundaries at playback time."""

    def __init__(self, callback: Callable[[int, int], None], volume: int = 100) -> None:
        if not hasattr(ctypes, "windll"):
            raise NaturalVoiceError("Natural Voice audio playback requires Windows")
        self._callback = callback
        self._winmm = ctypes.windll.winmm
        self._handle = ctypes.c_void_p()
        self._pending_audio = bytearray()
        self._audio_condition = threading.Condition()
        self._synthesis_finished = False
        self._boundaries: list[tuple[int, int, int]] = []
        self._boundary_lock = threading.Lock()
        self._done = threading.Event()
        self._stopped = threading.Event()
        self._paused = False
        self._played_bytes = 0
        self._submitted_bytes = 0
        self._volume = max(0, min(100, volume))
        self._started_at = 0.0

    def start(self) -> None:
        self._done.clear()
        self._stopped.clear()
        self._played_bytes = 0
        self._submitted_bytes = 0
        self._started_at = time.monotonic()
        with self._boundary_lock:
            self._boundaries.clear()
        with self._audio_condition:
            self._pending_audio.clear()
            self._synthesis_finished = False
        self._open()
        if self._paused:
            self._check(self._winmm.waveOutPause(self._handle), "pause audio")
        threading.Thread(
            target=self._run,
            daemon=True,
            name="NaturalVoiceAudio",
        ).start()

    def feed(self, data: bytes) -> None:
        if data and not self._stopped.is_set():
            with self._audio_condition:
                self._pending_audio.extend(data)
                self._audio_condition.notify_all()

    def add_boundary(self, offset_ticks: int, position: int, length: int) -> None:
        byte_offset = int(offset_ticks * BYTES_PER_SECOND / 10_000_000)
        with self._boundary_lock:
            self._boundaries.append((byte_offset, position, length))
            self._boundaries.sort(key=lambda item: item[0])

    def finish(self) -> None:
        with self._audio_condition:
            self._synthesis_finished = True
            self._audio_condition.notify_all()
        self._done.wait()

    def pause(self) -> None:
        self._paused = True
        if self._handle:
            self._check(self._winmm.waveOutPause(self._handle), "pause audio")

    def resume(self) -> None:
        self._paused = False
        if self._handle:
            self._check(self._winmm.waveOutRestart(self._handle), "resume audio")

    def stop(self) -> None:
        self._stopped.set()
        self._paused = False
        with self._audio_condition:
            self._synthesis_finished = True
            self._audio_condition.notify_all()
        if self._handle:
            self._winmm.waveOutReset(self._handle)
            self._done.wait(timeout=1)
        else:
            self._done.set()

    def _open(self) -> None:
        wave_format = _WaveFormat(1, 1, SAMPLE_RATE, BYTES_PER_SECOND, 2, 16, 0)
        result = self._winmm.waveOutOpen(
            ctypes.byref(self._handle),
            ctypes.c_uint(-1),
            ctypes.byref(wave_format),
            0,
            0,
            0,
        )
        self._check(result, "open the audio device")
        channel_volume = round(0xFFFF * self._volume / 100)
        stereo_volume = channel_volume | (channel_volume << 16)
        self._check(
            self._winmm.waveOutSetVolume(self._handle, stereo_volume),
            "set audio volume",
        )

    def _run(self) -> None:
        queued: deque[tuple[ctypes.Array[Any], _WaveHeader, int]] = deque()
        try:
            self._wait_for_prebuffer()
            if not self._stopped.is_set():
                with self._audio_condition:
                    buffered_bytes = len(self._pending_audio)
                log_event(
                    logger,
                    logging.INFO,
                    "natural_voice.playback.started",
                    buffered_bytes=buffered_bytes,
                    startup_ms=round((time.monotonic() - self._started_at) * 1000),
                )

            while not self._stopped.is_set():
                self._update_playback_position()
                self._release_completed(queued)
                self._emit_boundaries()

                while len(queued) < MAX_QUEUED_BUFFERS:
                    chunk = self._take_audio_block()
                    if chunk is None:
                        break
                    queued.append(self._submit_block(chunk))

                with self._audio_condition:
                    finished = self._synthesis_finished and not self._pending_audio
                if finished and not queued:
                    break

                with self._audio_condition:
                    if not self._pending_audio and not self._synthesis_finished:
                        self._audio_condition.wait(timeout=0.005)
                    else:
                        self._audio_condition.wait(timeout=0.002)

            if not self._stopped.is_set():
                self._played_bytes = self._submitted_bytes
                self._emit_boundaries()
        except Exception:
            logger.exception("Natural Voice audio playback failed")
        finally:
            if self._handle:
                self._winmm.waveOutReset(self._handle)
                while queued:
                    _, header, _ = queued.popleft()
                    self._winmm.waveOutUnprepareHeader(
                        self._handle,
                        ctypes.byref(header),
                        ctypes.sizeof(header),
                    )
                self._winmm.waveOutClose(self._handle)
                self._handle = ctypes.c_void_p()
            self._done.set()

    def _wait_for_prebuffer(self) -> None:
        with self._audio_condition:
            self._audio_condition.wait_for(
                lambda: (
                    self._stopped.is_set()
                    or self._synthesis_finished
                    or len(self._pending_audio) >= PREBUFFER_BYTES
                )
            )

    def _take_audio_block(self) -> bytes | None:
        with self._audio_condition:
            if len(self._pending_audio) >= PLAYBACK_BLOCK_BYTES:
                length = PLAYBACK_BLOCK_BYTES
            elif self._synthesis_finished and self._pending_audio:
                length = len(self._pending_audio)
            else:
                return None
            chunk = bytes(self._pending_audio[:length])
            del self._pending_audio[:length]
            return chunk

    def _submit_block(self, chunk: bytes) -> tuple[ctypes.Array[Any], _WaveHeader, int]:
        buffer = ctypes.create_string_buffer(chunk)
        header = _WaveHeader(ctypes.cast(buffer, ctypes.c_void_p), len(chunk))
        size = ctypes.sizeof(header)
        self._check(
            self._winmm.waveOutPrepareHeader(self._handle, ctypes.byref(header), size),
            "prepare audio",
        )
        try:
            self._check(
                self._winmm.waveOutWrite(self._handle, ctypes.byref(header), size),
                "play audio",
            )
        except Exception:
            self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(header), size)
            raise
        self._submitted_bytes += len(chunk)
        return buffer, header, len(chunk)

    def _release_completed(
        self, queued: deque[tuple[ctypes.Array[Any], _WaveHeader, int]]
    ) -> None:
        while queued and queued[0][1].dwFlags & WHDR_DONE:
            _, header, _ = queued.popleft()
            self._winmm.waveOutUnprepareHeader(
                self._handle,
                ctypes.byref(header),
                ctypes.sizeof(header),
            )

    def _update_playback_position(self) -> None:
        position = _MMTime(TIME_BYTES)
        result = self._winmm.waveOutGetPosition(
            self._handle, ctypes.byref(position), ctypes.sizeof(position)
        )
        if result:
            return
        if position.wType == TIME_BYTES:
            played_bytes = position.u.cb
        elif position.wType == TIME_SAMPLES:
            played_bytes = position.u.sample * BYTES_PER_SAMPLE
        elif position.wType == TIME_MS:
            played_bytes = int(position.u.ms * BYTES_PER_SECOND / 1000)
        else:
            return
        self._played_bytes = min(self._submitted_bytes, played_bytes)

    def _emit_boundaries(self) -> None:
        ready: list[tuple[int, int]] = []
        with self._boundary_lock:
            while self._boundaries and self._boundaries[0][0] <= self._played_bytes:
                _, position, length = self._boundaries.pop(0)
                ready.append((position, length))
        for position, length in ready:
            self._callback(position, length)

    @staticmethod
    def _check(result: int, action: str) -> None:
        if result:
            raise NaturalVoiceError(f"Could not {action} (winmm error {result})")


@dataclass(frozen=True, slots=True)
class _SpeechRequest:
    generation: int
    text: str


class _Engine(Protocol):
    def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class NaturalVoiceSpeaker:
    """Match the app's speaker contract using the direct embedded engine."""

    def __init__(
        self, config: AppConfig, word_callback: Callable[[str, int, int], None] | None
    ) -> None:
        self._config = config
        self._word_callback = word_callback
        self._condition = threading.Condition()
        self._queue: Queue[_SpeechRequest] = Queue()
        self._generation = 0
        self._active_generation: int | None = None
        self._completed_generation = 0
        self._paused = False
        self._failed = False
        self._player = WaveOutPlayer(self._on_played_word, config.speech_volume)
        self._engine: _Engine = NaturalVoiceEngine(
            config, self._player.feed, self._player.add_boundary
        )
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="NaturalVoiceSpeaker"
        )
        self._thread.start()

    @property
    def active(self) -> bool:
        with self._condition:
            return self._active_generation is not None

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    def speak(self, text: str) -> int | None:
        if len(text) < self._config.minimum_text_length:
            return None
        with self._condition:
            if self._failed:
                raise NaturalVoiceError("The Natural Voice worker has failed")
            self._generation += 1
            request = _SpeechRequest(self._generation, text)
            self._drain_queue()
            active = self._active_generation is not None
            self._queue.put(request)
            self._condition.notify_all()
        if active:
            self._player.stop()
            self._engine.stop()
        return request.generation

    def stop(self) -> None:
        with self._condition:
            self._generation += 1
            self._drain_queue()
            active = self._active_generation is not None
            self._paused = False
            self._condition.notify_all()
        if active:
            self._player.stop()
            self._engine.stop()

    def pause(self) -> None:
        with self._condition:
            if self._active_generation is None or self._paused:
                return
            self._paused = True
        self._player.pause()

    def resume(self) -> None:
        with self._condition:
            if not self._paused:
                return
            self._paused = False
        self._player.resume()

    def wait_until_done(self, generation: int) -> bool:
        with self._condition:
            self._condition.wait_for(
                lambda: (
                    self._failed
                    or self._generation != generation
                    or self._completed_generation >= generation
                )
            )
            return (
                not self._failed
                and self._generation == generation
                and self._completed_generation >= generation
            )

    def _run(self) -> None:
        while True:
            request = self._queue.get()
            if self._is_superseded(request.generation):
                continue
            try:
                self._speak_request(request)
            except Exception:
                if self._is_superseded(request.generation):
                    continue
                with self._condition:
                    self._failed = True
                    self._active_generation = None
                    self._paused = False
                    self._condition.notify_all()
                return

    def _speak_request(self, request: _SpeechRequest) -> None:
        with self._condition:
            self._active_generation = request.generation
            self._paused = False
        try:
            segments = [
                (match.start(), match.group())
                for match in re.finditer(r"[^\n]+", request.text)
            ]
            for index, (offset, segment) in enumerate(segments):
                if self._is_superseded(request.generation):
                    return
                spoken, prefix = strip_display_bullet_prefix(segment)
                self._segment_text = request.text
                self._segment_offset = offset + prefix
                self._player.start()
                self._engine.speak(spoken)
                self._player.finish()
                if index < len(segments) - 1 and not self._wait_pause(
                    request.generation
                ):
                    return
        finally:
            with self._condition:
                if self._active_generation == request.generation:
                    self._active_generation = None
                    self._paused = False
                if self._generation == request.generation:
                    self._completed_generation = request.generation
                self._condition.notify_all()

    def _on_played_word(self, position: int, length: int) -> None:
        if self._word_callback:
            self._word_callback(
                self._segment_text, self._segment_offset + position, length
            )

    def _wait_pause(self, generation: int) -> bool:
        remaining = self._config.structure_pause_seconds
        previous = time.monotonic()
        while remaining > 0:
            if self._is_superseded(generation):
                return False
            now = time.monotonic()
            with self._condition:
                if not self._paused:
                    remaining -= now - previous
            previous = now
            time.sleep(0.01)
        return True

    def _is_superseded(self, generation: int) -> bool:
        with self._condition:
            return self._generation != generation

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                return
