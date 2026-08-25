from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Final

from ..native import (
    AudioEventCallback,
    AudioRequestHandle,
    NativeAudioBoundary,
    NativeAudioEvent,
    NativeAudioEventKind,
    NativeAudioFormat,
    NativeAudioSubmitResult,
    NativeCallError,
    NativeSampleFormat,
    NativeStatus,
    check_native_status,
    get_native_bridge,
)
from .contracts import TerminalStatus

if TYPE_CHECKING:
    from .admission import AdmissionPolicy

logger = logging.getLogger(__name__)

UINT32_MAX: Final = (1 << 32) - 1
UINT64_MAX: Final = (1 << 64) - 1


class PcmSampleFormat(IntEnum):
    PCM_S16_LE = 1


@dataclass(frozen=True, slots=True)
class PcmFormat:
    sample_rate_hz: int
    channel_count: int = 1
    sample_format: PcmSampleFormat = PcmSampleFormat.PCM_S16_LE

    def __post_init__(self) -> None:
        if not 0 < self.sample_rate_hz <= UINT32_MAX:
            raise ValueError("sample_rate_hz must fit a nonzero uint32")
        if not 0 < self.channel_count <= UINT32_MAX:
            raise ValueError("channel_count must fit a nonzero uint32")
        try:
            sample_format = PcmSampleFormat(self.sample_format)
        except ValueError as error:
            raise ValueError("unsupported PCM sample format") from error
        object.__setattr__(self, "sample_format", sample_format)

    @property
    def bytes_per_frame(self) -> int:
        if self.sample_format is PcmSampleFormat.PCM_S16_LE:
            return self.channel_count * 2
        raise ValueError("unsupported PCM sample format")


@dataclass(frozen=True, slots=True)
class PcmBoundary:
    """A played-word boundary using slice-relative frames and request UTF-16 offsets."""

    frame_offset: int
    text_position: int
    text_length: int

    def __post_init__(self) -> None:
        if not 0 <= self.frame_offset <= UINT64_MAX:
            raise ValueError("frame_offset must fit uint64")
        if not 0 <= self.text_position <= UINT32_MAX:
            raise ValueError("text_position must fit uint32")
        if not 0 < self.text_length <= UINT32_MAX:
            raise ValueError("text_length must fit a nonzero uint32")


@dataclass(frozen=True, slots=True)
class PcmSubmitResult:
    accepted_frames: int
    buffered_frames_after_submit: int


@dataclass(frozen=True, slots=True)
class PcmStarted:
    request_id: int


@dataclass(frozen=True, slots=True)
class PcmPlayedWord:
    request_id: int
    text_position: int
    text_length: int


@dataclass(frozen=True, slots=True)
class PcmUnderrun:
    request_id: int
    buffered_frames: int


@dataclass(frozen=True, slots=True)
class PcmTerminal:
    request_id: int
    status: TerminalStatus
    error_code: int
    diagnostic: str = ""


PcmEvent = PcmStarted | PcmPlayedWord | PcmUnderrun | PcmTerminal
PcmEventCallback = Callable[[PcmEvent], None]


class PcmAdmissionInterrupted(RuntimeError):
    """Bounded submission was woken by stop, supersede, failure, or close.

    This is the ordinary way a producer learns its request is over while it is
    offering audio. It is not an error condition to report to the user.
    """

    def __init__(self, request_id: int, submitted_frames: int) -> None:
        self.request_id = request_id
        self.submitted_frames = submitted_frames
        super().__init__(
            f"PCM admission interrupted for request {request_id} "
            f"after {submitted_frames} accepted frames"
        )


def utf16_code_unit_offset(text: str, codepoint_offset: int) -> int:
    if not 0 <= codepoint_offset <= len(text):
        raise ValueError("codepoint_offset must identify an edge in the text")
    return len(text[:codepoint_offset].encode("utf-16-le")) // 2


def pcm_boundary_from_codepoints(
    text: str,
    frame_offset: int,
    text_position: int,
    text_length: int,
) -> PcmBoundary:
    if text_length <= 0 or text_position + text_length > len(text):
        raise ValueError("code-point boundary must fit the request text")
    start = utf16_code_unit_offset(text, text_position)
    end = utf16_code_unit_offset(text, text_position + text_length)
    return PcmBoundary(frame_offset, start, end - start)


class PcmPlaybackSession:
    """Own one request-scoped native PCM handle and its callback lifetime."""

    def __init__(
        self,
        request_id: int,
        request_text: str,
        pcm_format: PcmFormat,
        callback: PcmEventCallback,
        *,
        dll_path: str = "",
    ) -> None:
        if not 0 < request_id <= UINT64_MAX:
            raise ValueError("request_id must fit a nonzero uint64")
        text_length_utf16 = utf16_code_unit_offset(request_text, len(request_text))
        if text_length_utf16 > UINT32_MAX:
            raise ValueError("request text length must fit uint32 UTF-16 code units")

        self.request_id = request_id
        self.request_text = request_text
        self.pcm_format = pcm_format
        self._text_length_utf16 = text_length_utf16
        self._valid_text_edges = self._utf16_edges(request_text)
        self._event_callback = callback
        self._bridge = get_native_bridge(dll_path)
        self._dll = self._bridge.library
        self._state_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._callback_state = threading.local()
        self._handle = 0
        self._accepting = True
        self._started = False
        self._terminal = False
        self._closing = False
        self._closed = False
        # Set by any path that closes admission, so a producer blocked inside
        # bounded submission stops offering slices. The contract requires the
        # interrupting thread to be a different one from the blocked worker.
        self._interrupted = False
        self._native_callback = AudioEventCallback(self._on_native_event)

        native_format = NativeAudioFormat(
            ctypes.sizeof(NativeAudioFormat),
            pcm_format.sample_rate_hz,
            pcm_format.channel_count,
            NativeSampleFormat(pcm_format.sample_format),
        )
        handle = AudioRequestHandle()
        status = self._dll.ss_audio_request_create(
            request_id,
            ctypes.byref(native_format),
            text_length_utf16,
            self._native_callback,
            None,
            ctypes.byref(handle),
        )
        check_native_status(status, "create PCM playback session")
        if handle.value == 0:
            raise NativeCallError(
                "create PCM playback session",
                NativeStatus.INTERNAL_ERROR,
                "native returned success without a request handle",
            )
        self._handle = handle.value

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def submit(
        self,
        pcm: bytes | bytearray | memoryview,
        boundaries: Sequence[PcmBoundary] = (),
    ) -> PcmSubmitResult:
        self._ensure_not_callback()
        handle = self._operation_handle(require_accepting=True)
        payload = bytes(pcm)
        boundary_values = tuple(boundaries)
        frame_count = self._validate_submission(payload, boundary_values)

        pcm_buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload) if payload else None
        native_boundaries = (
            (NativeAudioBoundary * len(boundary_values))(
                *(
                    NativeAudioBoundary(
                        boundary.frame_offset,
                        boundary.text_position,
                        boundary.text_length,
                    )
                    for boundary in boundary_values
                )
            )
            if boundary_values
            else None
        )
        native_result = NativeAudioSubmitResult(
            ctypes.sizeof(NativeAudioSubmitResult),
            0,
            0,
            0,
        )
        status = self._dll.ss_audio_request_submit(
            AudioRequestHandle(handle),
            ctypes.cast(pcm_buffer, ctypes.c_void_p) if pcm_buffer is not None else None,
            len(payload),
            native_boundaries,
            len(boundary_values),
            ctypes.byref(native_result),
        )
        check_native_status(status, "submit PCM")
        if native_result.accepted_frames != frame_count:
            raise NativeCallError(
                "submit PCM",
                NativeStatus.INTERNAL_ERROR,
                "native accepted a partial PCM submission",
            )
        return PcmSubmitResult(
            native_result.accepted_frames,
            native_result.buffered_frames_after_submit,
        )

    def submit_bounded(
        self,
        pcm: bytes | bytearray | memoryview,
        boundaries: Sequence[PcmBoundary] = (),
        *,
        policy: AdmissionPolicy | None = None,
    ) -> PcmSubmitResult:
        """Submit PCM through bounded admission, slicing when it is oversized.

        Each slice is offered with the plain :meth:`submit` call, which the
        contract defines as synchronous and interruptibly blocking until native
        capacity admits it. Native performs the wait in Package J; this method
        never polls, sleeps, or asks native how much room is free before
        offering, because a separate wait/enqueue step would add a race without
        adding capability.

        Raises :class:`PcmAdmissionInterrupted` when stop, supersede, failure,
        or close ends the request while slices remain. Frames already accepted
        by native stay accepted; the caller stops producing rather than
        retrying.
        """
        from .admission import slice_for_admission

        self._ensure_not_callback()
        active_policy = policy or self._default_policy()
        slices = slice_for_admission(pcm, boundaries, self.pcm_format, active_policy)

        submitted_frames = 0
        buffered_frames = 0
        for admission_slice in slices:
            if self._admission_interrupted():
                raise PcmAdmissionInterrupted(self.request_id, submitted_frames)
            result = self.submit(admission_slice.pcm, admission_slice.boundaries)
            submitted_frames += result.accepted_frames
            buffered_frames = result.buffered_frames_after_submit
        return PcmSubmitResult(submitted_frames, buffered_frames)

    def needs_more_audio(
        self,
        buffered_frames: int,
        *,
        policy: AdmissionPolicy | None = None,
    ) -> bool:
        """Whether the producer should keep generating ahead of playback.

        Callers pass the ``buffered_frames_after_submit`` telemetry they
        already hold. This deliberately consults no native state: buffer
        telemetry is advisory, not a synchronization API.
        """
        active_policy = policy or self._default_policy()
        return active_policy.needs_more_audio(buffered_frames)

    def _default_policy(self) -> AdmissionPolicy:
        # Imported here because admission builds on this module's value types.
        from .admission import AdmissionPolicy as Policy

        return Policy.for_format(self.pcm_format)

    def _admission_interrupted(self) -> bool:
        with self._state_lock:
            return self._interrupted or self._closing or self._closed

    def finish_input(self) -> None:
        self._ensure_not_callback()
        handle = self._operation_handle(require_accepting=True)
        status = self._dll.ss_audio_request_finish_input(AudioRequestHandle(handle))
        check_native_status(status, "finish PCM input")
        with self._state_lock:
            self._accepting = False

    def pause(self) -> None:
        self._control("pause", self._dll.ss_audio_request_pause)

    def resume(self) -> None:
        self._control("resume", self._dll.ss_audio_request_resume)

    def stop(self, reason: TerminalStatus) -> None:
        if reason not in {
            TerminalStatus.CANCELLED,
            TerminalStatus.SUPERSEDED,
            TerminalStatus.FAILED,
            TerminalStatus.CLOSED,
        }:
            raise ValueError("stop reason must be cancelled, superseded, failed, or closed")
        self._ensure_not_callback()
        handle = self._operation_handle()
        status = self._dll.ss_audio_request_stop(AudioRequestHandle(handle), reason.value)
        check_native_status(status, "stop PCM playback")
        with self._state_lock:
            self._accepting = False
            self._interrupted = True

    def close(self) -> None:
        self._ensure_not_callback()
        with self._close_lock:
            with self._state_lock:
                if self._closed:
                    return
                self._closing = True
                self._interrupted = True
                handle = self._handle
            try:
                status = self._dll.ss_audio_request_destroy(AudioRequestHandle(handle))
            except Exception:
                with self._state_lock:
                    self._closing = False
                raise
            if status not in {NativeStatus.OK, NativeStatus.INVALID_HANDLE}:
                with self._state_lock:
                    self._closing = False
                check_native_status(status, "destroy PCM playback session")
            with self._state_lock:
                self._handle = 0
                self._accepting = False
                self._closing = False
                self._closed = True

    def __enter__(self) -> PcmPlaybackSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _control(self, action: str, function: Callable[[AudioRequestHandle], int]) -> None:
        self._ensure_not_callback()
        handle = self._operation_handle()
        status = function(AudioRequestHandle(handle))
        check_native_status(status, f"{action} PCM playback")

    def _operation_handle(self, *, require_accepting: bool = False) -> int:
        with self._state_lock:
            if self._closing or self._closed:
                raise RuntimeError("PCM playback session is closed")
            if require_accepting and not self._accepting:
                raise RuntimeError("PCM playback session is no longer accepting input")
            return self._handle

    def _ensure_not_callback(self) -> None:
        if getattr(self._callback_state, "active", False):
            raise RuntimeError("PCM playback controls cannot run from its event callback")

    def _validate_submission(
        self,
        pcm: bytes,
        boundaries: Sequence[PcmBoundary],
    ) -> int:
        if len(pcm) > UINT64_MAX:
            raise ValueError("PCM byte length must fit uint64")
        bytes_per_frame = self.pcm_format.bytes_per_frame
        if len(pcm) % bytes_per_frame:
            raise ValueError("PCM byte length must contain complete frames")
        if len(boundaries) > UINT32_MAX:
            raise ValueError("boundary count must fit uint32")
        frame_count = len(pcm) // bytes_per_frame
        previous_frame = 0
        for index, boundary in enumerate(boundaries):
            if boundary.frame_offset > frame_count:
                raise ValueError("boundary frame_offset exceeds submitted PCM frames")
            if index and boundary.frame_offset < previous_frame:
                raise ValueError("boundary frame_offset values must be nondecreasing")
            text_end = boundary.text_position + boundary.text_length
            if text_end > self._text_length_utf16:
                raise ValueError("boundary text range exceeds the complete request")
            if (
                boundary.text_position not in self._valid_text_edges
                or text_end not in self._valid_text_edges
            ):
                raise ValueError("boundary text range splits a UTF-16 surrogate pair")
            previous_frame = boundary.frame_offset
        return frame_count

    def _on_native_event(
        self,
        event_pointer: Any,
        _context: Any,
    ) -> None:
        try:
            self._deliver_native_event(event_pointer)
        except Exception:
            logger.exception("pcm.native_callback.failed request_id=%s", self.request_id)

    def _deliver_native_event(
        self,
        event_pointer: Any,
    ) -> None:
        if not event_pointer:
            logger.error("pcm.native_event.invalid request_id=%s reason=null", self.request_id)
            return
        native_event = event_pointer.contents
        if native_event.size < ctypes.sizeof(NativeAudioEvent):
            logger.error("pcm.native_event.invalid request_id=%s reason=size", self.request_id)
            return
        diagnostic = (native_event.diagnostic or b"").decode("utf-8", errors="replace")

        with self._state_lock:
            event = self._copy_event_locked(native_event, diagnostic)
        if event is None:
            return
        self._callback_state.active = True
        try:
            self._event_callback(event)
        except Exception:
            logger.exception(
                "pcm.event_callback.failed request_id=%s event=%s",
                self.request_id,
                type(event).__name__,
            )
        finally:
            self._callback_state.active = False

    def _copy_event_locked(
        self,
        native_event: NativeAudioEvent,
        diagnostic: str,
    ) -> PcmEvent | None:
        if self._closed or native_event.request_id != self.request_id or self._terminal:
            return None
        try:
            kind = NativeAudioEventKind(native_event.kind)
        except ValueError:
            logger.error(
                "pcm.native_event.invalid request_id=%s reason=kind value=%s",
                self.request_id,
                native_event.kind,
            )
            return None
        if kind is NativeAudioEventKind.STARTED:
            if self._started:
                return None
            self._started = True
            return PcmStarted(self.request_id)
        if not self._started:
            logger.error("pcm.native_event.invalid request_id=%s reason=before_started", self.request_id)
            return None
        if kind is NativeAudioEventKind.PLAYED_WORD:
            return PcmPlayedWord(
                self.request_id,
                native_event.text_position,
                native_event.text_length,
            )
        if kind is NativeAudioEventKind.UNDERRUN:
            return PcmUnderrun(self.request_id, native_event.buffered_frames)

        try:
            terminal_status = TerminalStatus(native_event.terminal_status)
        except ValueError:
            terminal_status = TerminalStatus.FAILED
            diagnostic = diagnostic or f"Unknown terminal status {native_event.terminal_status}"
        if terminal_status is TerminalStatus.NONE:
            terminal_status = TerminalStatus.FAILED
            diagnostic = diagnostic or "Native emitted the non-terminal sentinel"
        self._terminal = True
        self._accepting = False
        self._interrupted = True
        return PcmTerminal(
            self.request_id,
            terminal_status,
            native_event.status,
            diagnostic,
        )

    @staticmethod
    def _utf16_edges(text: str) -> frozenset[int]:
        edges = {0}
        offset = 0
        for character in text:
            offset += 2 if ord(character) > 0xFFFF else 1
            edges.add(offset)
        return frozenset(edges)
