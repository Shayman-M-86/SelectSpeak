from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from math import ceil
from statistics import median
from typing import Any

from .debug import SpeechDebugCallback, SpeechDebugEvent, with_queue_delay

BYTES_PER_SAMPLE = 2
MAX_QUEUED_BUFFERS = 4
TICKS_PER_SECOND = 10_000_000
WHDR_DONE = 0x00000001
TIME_MS = 0x0001
TIME_SAMPLES = 0x0002
TIME_BYTES = 0x0004

logger = logging.getLogger(__name__)


class PcmPlaybackError(RuntimeError):
    pass


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


_QueuedBlock = tuple[ctypes.Array[Any], _WaveHeader, int]


@dataclass(slots=True)
class _PlaybackTelemetry:
    """Temporary old-path measurements retained until Package O."""

    feed_sizes: list[int] = field(default_factory=list)
    max_pending_bytes: int = 0
    loop_iterations: int = 0
    position_queries: int = 0
    blocks_submitted: int = 0
    boundary_delays_ms: list[float] = field(default_factory=list)
    underruns: int = 0
    stop_reset_ms: float | None = None
    started_process_time: float = 0.0
    started_thread_count: int = 0
    peak_thread_count: int = 0

    def reset(self, *, process_time: float, thread_count: int) -> None:
        self.feed_sizes.clear()
        self.max_pending_bytes = 0
        self.loop_iterations = 0
        self.position_queries = 0
        self.blocks_submitted = 0
        self.boundary_delays_ms.clear()
        self.underruns = 0
        self.stop_reset_ms = None
        self.started_process_time = process_time
        self.started_thread_count = thread_count
        self.peak_thread_count = thread_count

    @staticmethod
    def distribution(values: list[int] | list[float]) -> tuple[float, float, float, float]:
        if not values:
            return 0.0, 0.0, 0.0, 0.0
        ordered = sorted(values)
        p95_index = max(0, ceil(len(ordered) * 0.95) - 1)
        return float(ordered[0]), float(median(ordered)), float(ordered[p95_index]), float(ordered[-1])


class WaveOutPlayer:
    """Play one persistent PCM stream and emit text boundaries at playback time."""

    def __init__(
        self,
        callback: Callable[[int, int], None],
        volume: int = 100,
        sample_rate: int = 24_000,
        backend_name: str = "natural",
        debug_callback: SpeechDebugCallback | None = None,
    ) -> None:
        if not hasattr(ctypes, "windll"):
            raise PcmPlaybackError("PCM audio playback requires Windows")
        self._callback = callback
        self._winmm = ctypes.windll.winmm
        self._handle = ctypes.c_void_p()
        self._pending_audio = bytearray()
        self._audio_condition = threading.Condition()
        self._synthesis_finished = False
        self._boundaries: list[tuple[int, int, int]] = []
        self._boundary_lock = threading.Lock()
        self._done = threading.Event()
        self._playback_started = threading.Event()
        self._stopped = threading.Event()
        self._paused = False
        self._played_bytes = 0
        self._submitted_bytes = 0
        self._fed_bytes = 0
        self._volume = max(0, min(100, volume))
        self._sample_rate = sample_rate
        self._backend_name = backend_name
        self._debug_callback = debug_callback
        self._debug_markers: list[tuple[int, SpeechDebugEvent, float]] = []
        self._debug_lock = threading.Lock()
        self._bytes_per_second = sample_rate * BYTES_PER_SAMPLE
        self._playback_block_bytes = self._bytes_per_second // 10
        self._prebuffer_bytes = self._playback_block_bytes * 2
        self._started_at = 0.0
        self._telemetry = _PlaybackTelemetry()

    @property
    def fed_bytes(self) -> int:
        with self._audio_condition:
            return self._fed_bytes

    @property
    def buffered_seconds(self) -> float:
        with self._audio_condition:
            return max(0, self._fed_bytes - self._played_bytes) / self._bytes_per_second

    def start(self) -> None:
        self._done.clear()
        self._playback_started.clear()
        self._stopped.clear()
        self._played_bytes = 0
        self._submitted_bytes = 0
        self._fed_bytes = 0
        self._started_at = time.monotonic()
        thread_count = threading.active_count()
        self._telemetry.reset(process_time=time.process_time(), thread_count=thread_count)
        with self._boundary_lock:
            self._boundaries.clear()
        with self._debug_lock:
            self._debug_markers.clear()
        with self._audio_condition:
            self._pending_audio.clear()
            self._synthesis_finished = False
        self._open()
        if self._paused:
            self._check(self._winmm.waveOutPause(self._handle), "pause audio")
        threading.Thread(
            target=self._run,
            daemon=True,
            name=f"{self._backend_name.title()}VoiceAudio",
        ).start()

    def feed(self, data: bytes) -> None:
        if data and not self._stopped.is_set():
            with self._audio_condition:
                self._pending_audio.extend(data)
                self._fed_bytes += len(data)
                self._telemetry.feed_sizes.append(len(data))
                self._telemetry.max_pending_bytes = max(
                    self._telemetry.max_pending_bytes,
                    len(self._pending_audio),
                )
                self._audio_condition.notify_all()

    def feed_silence(self, seconds: float) -> None:
        byte_count = round(max(0.0, seconds) * self._bytes_per_second)
        # PCM16 must end on a complete sample.
        byte_count -= byte_count % BYTES_PER_SAMPLE
        if byte_count:
            self.feed(bytes(byte_count))

    def add_boundary(
        self,
        offset_ticks: int,
        position: int,
        length: int,
        *,
        base_byte_offset: int = 0,
    ) -> None:
        relative_bytes = int(offset_ticks * self._bytes_per_second / TICKS_PER_SECOND)
        self.add_boundary_at_byte(base_byte_offset + relative_bytes, position, length)

    def add_boundary_at_byte(self, byte_offset: int, position: int, length: int) -> None:
        with self._boundary_lock:
            self._boundaries.append((byte_offset, position, length))
            self._boundaries.sort(key=lambda item: item[0])

    def add_debug_marker(
        self,
        byte_offset: int,
        event: SpeechDebugEvent,
        *,
        generated_at: float | None = None,
    ) -> None:
        if self._debug_callback is None:
            return
        with self._debug_lock:
            self._debug_markers.append((byte_offset, event, generated_at or time.monotonic()))
            self._debug_markers.sort(key=lambda item: item[0])

    def finish(self) -> None:
        with self._audio_condition:
            self._synthesis_finished = True
            self._audio_condition.notify_all()
        self._done.wait()

    def wait_until_started(self, timeout: float = 2.0) -> bool:
        return self._playback_started.wait(timeout)

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
            reset_started_at = time.monotonic()
            self._winmm.waveOutReset(self._handle)
            self._telemetry.stop_reset_ms = (time.monotonic() - reset_started_at) * 1000
            self._done.wait(timeout=1)
        else:
            self._done.set()

    def _open(self) -> None:
        wave_format = _WaveFormat(
            1,
            1,
            self._sample_rate,
            self._bytes_per_second,
            BYTES_PER_SAMPLE,
            16,
            0,
        )
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
        queued: deque[_QueuedBlock] = deque()
        underrun_started_at: float | None = None
        try:
            self._wait_for_prebuffer()
            self._mark_playback_started()

            while not self._stopped.is_set():
                self._telemetry.loop_iterations += 1
                self._telemetry.peak_thread_count = max(
                    self._telemetry.peak_thread_count,
                    threading.active_count(),
                )
                self._process_playback_updates(queued)
                self._fill_playback_queue(queued)
                if self._playback_finished(queued):
                    break
                underrun_started_at = self._handle_buffer_state(queued, underrun_started_at)

            self._finish_playback_events()
        except Exception:
            logger.exception("PCM audio playback failed")
        finally:
            self._cleanup_playback(queued, underrun_started_at)

    def _mark_playback_started(self) -> None:
        if self._stopped.is_set():
            return
        with self._audio_condition:
            buffered_bytes = len(self._pending_audio)
        logger.info(
            "audio.playback.started backend=%s buffered_bytes=%s startup_ms=%s",
            self._backend_name,
            buffered_bytes,
            round((time.monotonic() - self._started_at) * 1000),
        )
        self._playback_started.set()

    def _process_playback_updates(self, queued: deque[_QueuedBlock]) -> None:
        self._update_playback_position()
        self._release_completed(queued)
        self._emit_boundaries()
        self._emit_debug_markers()

    def _fill_playback_queue(self, queued: deque[_QueuedBlock]) -> None:
        while len(queued) < MAX_QUEUED_BUFFERS:
            chunk = self._take_audio_block()
            if chunk is None:
                return
            queued.append(self._submit_block(chunk))

    def _playback_finished(self, queued: deque[_QueuedBlock]) -> bool:
        with self._audio_condition:
            return self._synthesis_finished and not self._pending_audio and not queued

    def _handle_buffer_state(
        self,
        queued: deque[_QueuedBlock],
        underrun_started_at: float | None,
    ) -> float | None:
        with self._audio_condition:
            starved = not queued and not self._pending_audio and not self._synthesis_finished
            now = time.monotonic()
            if starved and underrun_started_at is None:
                underrun_started_at = now
            elif not starved and underrun_started_at is not None:
                self._log_underrun(underrun_started_at, now)
                underrun_started_at = None
            timeout = 0.005 if not self._pending_audio and not self._synthesis_finished else 0.002
            self._audio_condition.wait(timeout=timeout)
        return underrun_started_at

    def _finish_playback_events(self) -> None:
        if self._stopped.is_set():
            return
        self._played_bytes = self._submitted_bytes
        self._emit_boundaries()
        self._emit_debug_markers()

    def _cleanup_playback(
        self,
        queued: deque[_QueuedBlock],
        underrun_started_at: float | None,
    ) -> None:
        if underrun_started_at is not None:
            self._log_underrun(underrun_started_at, time.monotonic())
        self._playback_started.set()
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
        logger.info(
            "audio.playback.finished backend=%s played_bytes=%s audio_seconds=%s elapsed_ms=%s stopped=%s",
            self._backend_name,
            self._played_bytes,
            round(self._played_bytes / self._bytes_per_second, 3),
            round((time.monotonic() - self._started_at) * 1000),
            self._stopped.is_set(),
        )
        self._log_telemetry()
        self._done.set()

    def _log_underrun(self, started_at: float, ended_at: float) -> None:
        duration_ms = round((ended_at - started_at) * 1000)
        if duration_ms >= 20:
            self._telemetry.underruns += 1
            logger.warning(
                "audio.playback.underrun backend=%s duration_ms=%s buffered_seconds=%s",
                self._backend_name,
                duration_ms,
                round(self.buffered_seconds, 3),
            )
            if self._debug_callback:
                self._debug_callback(
                    SpeechDebugEvent(
                        kind="underrun",
                        backend=self._backend_name,
                        delay_ms=duration_ms,
                        runway_ms=round(self.buffered_seconds * 1000),
                        message="Playback caught the synthesis buffer",
                    )
                )

    def _wait_for_prebuffer(self) -> None:
        with self._audio_condition:
            self._audio_condition.wait_for(
                lambda: (
                    self._stopped.is_set()
                    or self._synthesis_finished
                    or len(self._pending_audio) >= self._prebuffer_bytes
                )
            )

    def _take_audio_block(self) -> bytes | None:
        with self._audio_condition:
            if len(self._pending_audio) >= self._playback_block_bytes:
                length = self._playback_block_bytes
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
        self._telemetry.blocks_submitted += 1
        return buffer, header, len(chunk)

    def _release_completed(self, queued: deque[_QueuedBlock]) -> None:
        while queued and queued[0][1].dwFlags & WHDR_DONE:
            _, header, _ = queued.popleft()
            self._winmm.waveOutUnprepareHeader(
                self._handle,
                ctypes.byref(header),
                ctypes.sizeof(header),
            )

    def _update_playback_position(self) -> None:
        self._telemetry.position_queries += 1
        position = _MMTime(TIME_BYTES)
        result = self._winmm.waveOutGetPosition(self._handle, ctypes.byref(position), ctypes.sizeof(position))
        if result:
            return
        if position.wType == TIME_BYTES:
            played_bytes = position.u.cb
        elif position.wType == TIME_SAMPLES:
            played_bytes = position.u.sample * BYTES_PER_SAMPLE
        elif position.wType == TIME_MS:
            played_bytes = int(position.u.ms * self._bytes_per_second / 1000)
        else:
            return
        with self._audio_condition:
            self._played_bytes = min(self._submitted_bytes, played_bytes)
            self._audio_condition.notify_all()

    def _emit_boundaries(self) -> None:
        ready: list[tuple[int, int]] = []
        position_observed_at = time.monotonic()
        with self._boundary_lock:
            while self._boundaries and self._boundaries[0][0] <= self._played_bytes:
                _, position, length = self._boundaries.pop(0)
                ready.append((position, length))
        for position, length in ready:
            self._telemetry.boundary_delays_ms.append((time.monotonic() - position_observed_at) * 1000)
            self._callback(position, length)

    def _log_telemetry(self) -> None:
        elapsed_seconds = max(0.0, time.monotonic() - self._started_at)
        process_seconds = max(0.0, time.process_time() - self._telemetry.started_process_time)
        process_cpu_pct = process_seconds / elapsed_seconds * 100 if elapsed_seconds else 0.0
        feed_min, feed_median, feed_p95, feed_max = self._telemetry.distribution(
            self._telemetry.feed_sizes
        )
        delay_min, delay_median, delay_p95, delay_max = self._telemetry.distribution(
            self._telemetry.boundary_delays_ms
        )
        logger.info(
            "audio.playback.telemetry backend=%s feed_count=%s feed_size_bytes_min=%s "
            "feed_size_bytes_median=%s feed_size_bytes_p95=%s feed_size_bytes_max=%s "
            "total_fed_bytes=%s max_pending_bytes=%s loop_iterations=%s position_queries=%s "
            "blocks_submitted=%s boundary_count=%s boundary_delay_ms_min=%.3f "
            "boundary_delay_ms_median=%.3f boundary_delay_ms_p95=%.3f "
            "boundary_delay_ms_max=%.3f underruns=%s stop_reset_ms=%s process_cpu_pct=%.2f "
            "threads_start=%s threads_peak=%s threads_finish=%s",
            self._backend_name,
            len(self._telemetry.feed_sizes),
            round(feed_min),
            round(feed_median),
            round(feed_p95),
            round(feed_max),
            self._fed_bytes,
            self._telemetry.max_pending_bytes,
            self._telemetry.loop_iterations,
            self._telemetry.position_queries,
            self._telemetry.blocks_submitted,
            len(self._telemetry.boundary_delays_ms),
            delay_min,
            delay_median,
            delay_p95,
            delay_max,
            self._telemetry.underruns,
            None if self._telemetry.stop_reset_ms is None else round(self._telemetry.stop_reset_ms, 3),
            process_cpu_pct,
            self._telemetry.started_thread_count,
            self._telemetry.peak_thread_count,
            threading.active_count(),
        )

    def _emit_debug_markers(self) -> None:
        if self._debug_callback is None:
            return
        ready: list[tuple[SpeechDebugEvent, float]] = []
        with self._debug_lock:
            while self._debug_markers and self._debug_markers[0][0] <= self._played_bytes:
                _, event, generated_at = self._debug_markers.pop(0)
                ready.append((event, generated_at))
        played_at = time.monotonic()
        for event, generated_at in ready:
            self._debug_callback(with_queue_delay(event, generated_at, played_at))

    @staticmethod
    def _check(result: int, action: str) -> None:
        if result:
            raise PcmPlaybackError(f"Could not {action} (winmm error {result})")
