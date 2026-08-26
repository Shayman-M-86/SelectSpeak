import ctypes
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from selectspeak.native import (
    NativeAudioEvent,
    NativeAudioEventKind,
    NativeAudioSubmitResult,
    NativeStatus,
)
from selectspeak.speech import pcm as pcm_module
from selectspeak.speech.admission import AdmissionPolicy
from selectspeak.speech.contracts import TerminalStatus
from selectspeak.speech.pcm import (
    PcmBoundary,
    PcmFormat,
    PcmPlaybackSession,
    PcmPlayedWord,
    PcmStarted,
    PcmSubmitResult,
    PcmTerminal,
    PcmUnderrun,
    pcm_boundary_from_codepoints,
    utf16_code_unit_offset,
)

RUNTIME_NATIVE_DLL = Path(__file__).parents[1] / ".runtime" / "native" / "selectspeak_native.dll"


class _FakeAudioDll:
    def __init__(self, *, emit_started: bool = True) -> None:
        self.emit_started = emit_started
        self.callback: Any = None
        self.request_id = 0
        self.text_length_utf16 = 0
        self.format: tuple[int, int, int] | None = None
        self.submissions: list[tuple[bytes, list[tuple[int, int, int]]]] = []
        self.finish_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.stop_reasons: list[int] = []
        self.destroy_calls = 0
        self.terminal_on_destroy = False

    def ss_audio_request_create(
        self,
        request_id: int,
        pcm_format: Any,
        text_length_utf16: int,
        callback: Any,
        _context: Any,
        handle: Any,
    ) -> int:
        native_format = pcm_format._obj
        self.request_id = request_id
        self.text_length_utf16 = text_length_utf16
        self.format = (
            native_format.sample_rate_hz,
            native_format.channel_count,
            native_format.sample_format,
        )
        self.callback = callback
        ctypes.cast(handle, ctypes.POINTER(ctypes.c_uint64)).contents.value = 41
        if self.emit_started:
            self.emit(NativeAudioEventKind.STARTED)
        return NativeStatus.OK

    def ss_audio_request_submit(
        self,
        _handle: Any,
        pcm: Any,
        pcm_byte_length: int,
        boundaries: Any,
        boundary_count: int,
        result: Any,
    ) -> int:
        payload = ctypes.string_at(pcm, pcm_byte_length) if pcm_byte_length else b""
        copied_boundaries = [
            (
                boundaries[index].frame_offset,
                boundaries[index].text_position,
                boundaries[index].text_length,
            )
            for index in range(boundary_count)
        ]
        self.submissions.append((payload, copied_boundaries))
        native_result = ctypes.cast(
            result,
            ctypes.POINTER(NativeAudioSubmitResult),
        ).contents
        native_result.accepted_frames = pcm_byte_length // 2
        native_result.buffered_frames_after_submit = 17
        return NativeStatus.OK

    def ss_audio_request_finish_input(self, _handle: Any) -> int:
        self.finish_calls += 1
        return NativeStatus.OK

    def ss_audio_request_pause(self, _handle: Any) -> int:
        self.pause_calls += 1
        return NativeStatus.OK

    def ss_audio_request_resume(self, _handle: Any) -> int:
        self.resume_calls += 1
        return NativeStatus.OK

    def ss_audio_request_stop(self, _handle: Any, reason: int) -> int:
        self.stop_reasons.append(reason)
        return NativeStatus.OK

    def ss_audio_request_destroy(self, _handle: Any) -> int:
        self.destroy_calls += 1
        if self.terminal_on_destroy:
            self.emit(
                NativeAudioEventKind.TERMINAL,
                terminal_status=TerminalStatus.CLOSED,
            )
        return NativeStatus.OK

    def emit(
        self,
        kind: NativeAudioEventKind,
        *,
        request_id: int | None = None,
        terminal_status: TerminalStatus = TerminalStatus.NONE,
        status: int = NativeStatus.OK,
        text_position: int = 0,
        text_length: int = 0,
        buffered_frames: int = 0,
        diagnostic: bytes = b"",
    ) -> None:
        event = NativeAudioEvent(
            ctypes.sizeof(NativeAudioEvent),
            kind,
            self.request_id if request_id is None else request_id,
            terminal_status,
            status,
            text_position,
            text_length,
            buffered_frames,
            diagnostic,
        )
        self.callback(ctypes.byref(event), None)


def _session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "A😀B",
    callback: Any = None,
    emit_started: bool = True,
) -> tuple[PcmPlaybackSession, _FakeAudioDll, list[Any]]:
    dll = _FakeAudioDll(emit_started=emit_started)
    events: list[Any] = []
    monkeypatch.setattr(
        pcm_module,
        "get_native_bridge",
        lambda _path: SimpleNamespace(library=dll),
    )
    session = PcmPlaybackSession(
        7,
        text,
        PcmFormat(24_000),
        callback or events.append,
    )
    return session, dll, events


def test_session_creates_one_native_request_with_utf16_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, events = _session(monkeypatch)

    assert dll.request_id == 7
    assert dll.text_length_utf16 == 4
    assert dll.format == (24_000, 1, 1)
    assert events == [PcmStarted(7)]
    session.close()


def test_submit_copies_pcm_and_boundaries_and_returns_frame_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, _events = _session(monkeypatch)
    payload = bytearray(b"\x01\x00\x02\x00\x03\x00\x04\x00")
    boundaries = [PcmBoundary(0, 0, 1), PcmBoundary(2, 1, 2)]

    result = session.submit(payload, boundaries)
    payload[:] = bytes(len(payload))

    assert result == PcmSubmitResult(4, 17)
    assert dll.submissions == [
        (
            b"\x01\x00\x02\x00\x03\x00\x04\x00",
            [(0, 0, 1), (2, 1, 2)],
        )
    ]
    session.finish_input()
    assert dll.finish_calls == 1
    with pytest.raises(RuntimeError, match="no longer accepting"):
        session.submit(b"\x00\x00")
    session.close()


@pytest.mark.parametrize(
    ("payload", "boundaries", "message"),
    [
        (b"\x00", [], "complete frames"),
        (b"\x00\x00", [PcmBoundary(2, 0, 1)], "exceeds submitted"),
        (
            b"\x00\x00" * 2,
            [PcmBoundary(2, 0, 1), PcmBoundary(1, 1, 2)],
            "nondecreasing",
        ),
        (b"\x00\x00", [PcmBoundary(0, 3, 2)], "exceeds the complete request"),
        (b"\x00\x00", [PcmBoundary(0, 2, 1)], "surrogate pair"),
    ],
)
def test_submit_rejects_invalid_pcm_or_boundaries_before_native_call(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    boundaries: list[PcmBoundary],
    message: str,
) -> None:
    session, dll, _events = _session(monkeypatch)

    with pytest.raises(ValueError, match=message):
        session.submit(payload, boundaries)

    assert dll.submissions == []
    session.close()


def test_native_events_are_copied_ordered_and_suppressed_after_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, events = _session(monkeypatch)

    dll.emit(NativeAudioEventKind.PLAYED_WORD, text_position=1, text_length=2)
    dll.emit(NativeAudioEventKind.UNDERRUN, buffered_frames=9)
    dll.emit(
        NativeAudioEventKind.TERMINAL,
        terminal_status=TerminalStatus.FAILED,
        status=NativeStatus.DEVICE_ERROR,
        diagnostic=b"Device was removed",
    )
    dll.emit(NativeAudioEventKind.PLAYED_WORD, text_position=3, text_length=1)

    assert events == [
        PcmStarted(7),
        PcmPlayedWord(7, 1, 2),
        PcmUnderrun(7, 9),
        PcmTerminal(7, TerminalStatus.FAILED, NativeStatus.DEVICE_ERROR, "Device was removed"),
    ]
    with pytest.raises(RuntimeError, match="no longer accepting"):
        session.submit(b"\x00\x00")
    session.close()


def test_native_events_validate_request_identity_and_started_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, events = _session(monkeypatch, emit_started=False)

    dll.emit(NativeAudioEventKind.PLAYED_WORD, text_position=0, text_length=1)
    dll.emit(NativeAudioEventKind.STARTED, request_id=99)
    dll.emit(NativeAudioEventKind.STARTED)
    dll.emit(NativeAudioEventKind.STARTED)
    dll.emit(
        NativeAudioEventKind.TERMINAL,
        terminal_status=TerminalStatus.COMPLETED,
    )
    dll.emit(
        NativeAudioEventKind.TERMINAL,
        terminal_status=TerminalStatus.FAILED,
    )

    assert events == [PcmStarted(7), PcmTerminal(7, TerminalStatus.COMPLETED, 0)]
    session.close()


def test_user_callback_failure_never_crosses_the_native_callback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    received: list[Any] = []

    def failing_callback(event: Any) -> None:
        received.append(event)
        raise RuntimeError("consumer failed")

    session, dll, _events = _session(monkeypatch, callback=failing_callback)

    dll.emit(NativeAudioEventKind.PLAYED_WORD, text_position=0, text_length=1)
    dll.emit(
        NativeAudioEventKind.TERMINAL,
        terminal_status=TerminalStatus.COMPLETED,
    )

    assert [type(event) for event in received] == [PcmStarted, PcmPlayedWord, PcmTerminal]
    assert "pcm.event_callback.failed" in caplog.text
    session.close()


def test_controls_are_native_and_forbidden_from_the_event_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback_errors: list[Exception] = []
    session_holder: list[PcmPlaybackSession] = []

    def callback(event: Any) -> None:
        if isinstance(event, PcmPlayedWord):
            try:
                session_holder[0].pause()
            except Exception as error:
                callback_errors.append(error)

    session, dll, _events = _session(monkeypatch, callback=callback)
    session_holder.append(session)
    session.pause()
    session.resume()
    dll.emit(NativeAudioEventKind.PLAYED_WORD, text_position=0, text_length=1)
    session.stop(TerminalStatus.CANCELLED)

    assert dll.pause_calls == 1
    assert dll.resume_calls == 1
    assert dll.stop_reasons == [TerminalStatus.CANCELLED]
    assert len(callback_errors) == 1
    assert "cannot run from its event callback" in str(callback_errors[0])
    session.close()


def test_close_retains_callbacks_through_destroy_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, events = _session(monkeypatch)
    dll.terminal_on_destroy = True

    session.close()
    session.close()

    assert events == [PcmStarted(7), PcmTerminal(7, TerminalStatus.CLOSED, 0)]
    assert dll.destroy_calls == 1
    assert session.closed
    dll.emit(NativeAudioEventKind.PLAYED_WORD, text_position=0, text_length=1)
    assert len(events) == 2
    with pytest.raises(RuntimeError, match="session is closed"):
        session.pause()


def test_utf16_helpers_convert_codepoint_boundaries_without_splitting_surrogates() -> None:
    text = "A😀B"

    assert [utf16_code_unit_offset(text, index) for index in range(4)] == [0, 1, 3, 4]
    assert pcm_boundary_from_codepoints(text, 12, 1, 1) == PcmBoundary(12, 1, 2)


@pytest.mark.skipif(
    sys.platform != "win32" or not RUNTIME_NATIVE_DLL.is_file(),
    reason="built Windows native bridge is unavailable",
)
def test_staged_package_j_engine_accepts_and_closes_a_session() -> None:
    events: list[Any] = []
    started = threading.Event()

    def on_event(event: Any) -> None:
        events.append(event)
        if isinstance(event, PcmStarted):
            started.set()

    session = PcmPlaybackSession(
        1,
        "Read this",
        PcmFormat(24_000),
        on_event,
        dll_path=str(RUNTIME_NATIVE_DLL),
    )

    assert started.wait(2)
    session.close()

    assert events == [
        PcmStarted(1),
        PcmTerminal(1, TerminalStatus.CLOSED, NativeStatus.OK),
    ]


class _BlockingAudioDll(_FakeAudioDll):
    """A fake whose submit blocks, standing in for native bounded capacity.

    Package J implements the real interruptible wait inside native. This models
    only the visible contract: submit does not return until capacity admits the
    slice, and a control thread is what releases it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.capacity = threading.Event()
        self.entered_submit = threading.Event()

    def ss_audio_request_submit(
        self,
        _handle: Any,
        pcm: Any,
        pcm_byte_length: int,
        boundaries: Any,
        boundary_count: int,
        result: Any,
    ) -> int:
        self.entered_submit.set()
        self.capacity.wait(5)
        return super().ss_audio_request_submit(
            _handle, pcm, pcm_byte_length, boundaries, boundary_count, result
        )


def test_bounded_submit_slices_oversized_pcm(monkeypatch: pytest.MonkeyPatch) -> None:
    session, dll, _ = _session(monkeypatch)
    policy = AdmissionPolicy(low_water_frames=10, high_water_frames=100, hard_capacity_frames=200)

    result = session.submit_bounded(b"\x01\x02" * 250, policy=policy)

    assert len(dll.submissions) == 3
    assert result.accepted_frames == 250
    assert b"".join(payload for payload, _ in dll.submissions) == b"\x01\x02" * 250


def test_bounded_submit_reports_the_latest_buffer_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, _ = _session(monkeypatch)

    result = session.submit_bounded(b"\x01\x02" * 40)

    assert result.buffered_frames_after_submit == 17


def test_bounded_submit_uses_one_call_when_the_slice_already_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, _ = _session(monkeypatch)

    session.submit_bounded(b"\x01\x02" * 40)

    assert len(dll.submissions) == 1


def test_bounded_submit_carries_boundaries_onto_their_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, _ = _session(monkeypatch)
    policy = AdmissionPolicy(low_water_frames=10, high_water_frames=100, hard_capacity_frames=200)
    boundaries = [PcmBoundary(0, 0, 1), PcmBoundary(120, 1, 2)]

    session.submit_bounded(b"\x01\x02" * 250, boundaries, policy=policy)

    assert dll.submissions[0][1] == [(0, 0, 1)]
    assert dll.submissions[1][1] == [(20, 1, 2)]
    assert dll.submissions[2][1] == []


def test_stop_interrupts_a_producer_between_slices(monkeypatch: pytest.MonkeyPatch) -> None:
    session, dll, _ = _session(monkeypatch)
    policy = AdmissionPolicy(low_water_frames=10, high_water_frames=100, hard_capacity_frames=200)
    session.stop(TerminalStatus.CANCELLED)

    with pytest.raises(pcm_module.PcmAdmissionInterrupted) as error:
        session.submit_bounded(b"\x01\x02" * 250, policy=policy)

    assert error.value.request_id == 7
    assert dll.submissions == []


def test_a_control_thread_releases_a_blocked_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dll = _BlockingAudioDll()
    monkeypatch.setattr(
        pcm_module,
        "get_native_bridge",
        lambda _path: SimpleNamespace(library=dll),
    )
    session = PcmPlaybackSession(7, "A😀B", PcmFormat(24_000), lambda _event: None)
    failures: list[BaseException] = []

    def produce() -> None:
        try:
            session.submit_bounded(b"\x01\x02" * 40)
        except BaseException as error:  # noqa: BLE001 - recorded for the assertion
            failures.append(error)

    worker = threading.Thread(target=produce)
    worker.start()
    assert dll.entered_submit.wait(5)

    # The blocked worker must never be responsible for interrupting itself.
    dll.capacity.set()
    worker.join(5)

    assert not worker.is_alive()
    assert failures == []


def test_close_stops_a_producer_from_offering_further_slices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, _ = _session(monkeypatch)
    policy = AdmissionPolicy(low_water_frames=10, high_water_frames=100, hard_capacity_frames=200)
    session.close()

    with pytest.raises(pcm_module.PcmAdmissionInterrupted):
        session.submit_bounded(b"\x01\x02" * 250, policy=policy)


def test_a_terminal_event_interrupts_further_bounded_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, dll, _ = _session(monkeypatch)
    policy = AdmissionPolicy(low_water_frames=10, high_water_frames=100, hard_capacity_frames=200)
    dll.emit(NativeAudioEventKind.TERMINAL, terminal_status=TerminalStatus.SUPERSEDED)

    with pytest.raises(pcm_module.PcmAdmissionInterrupted):
        session.submit_bounded(b"\x01\x02" * 250, policy=policy)


def test_bounded_submit_is_rejected_from_the_event_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[BaseException] = []

    def callback(event: Any) -> None:
        try:
            session.submit_bounded(b"\x01\x02" * 10)
        except BaseException as error:  # noqa: BLE001 - recorded for the assertion
            failures.append(error)

    session, dll, _ = _session(monkeypatch, callback=callback, emit_started=False)
    dll.emit(NativeAudioEventKind.STARTED)

    assert failures and isinstance(failures[0], RuntimeError)


def test_needs_more_audio_follows_the_low_water_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, _ = _session(monkeypatch)
    policy = AdmissionPolicy(low_water_frames=10, high_water_frames=100, hard_capacity_frames=200)

    assert session.needs_more_audio(9, policy=policy)
    assert not session.needs_more_audio(10, policy=policy)
