import ctypes
import sys
from pathlib import Path
from typing import Any

import pytest

from selectspeak.native import (
    NATIVE_API_VERSION,
    AudioEventCallback,
    AudioRequestHandle,
    NativeAudioBoundary,
    NativeAudioEvent,
    NativeAudioEventKind,
    NativeAudioFormat,
    NativeAudioSubmitResult,
    NativeBridge,
    NativeCallError,
    NativeNaturalSynthesisResult,
    NativeSampleFormat,
    NativeStatus,
    NativeTerminalStatus,
    check_native_status,
)
from selectspeak.native import bindings as native_bindings
from selectspeak.speech.contracts import TerminalStatus

RUNTIME_NATIVE_DLL = Path(__file__).parents[1] / ".runtime" / "native" / "selectspeak_native.dll"


class _FakeFunction:
    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.argtypes: list[Any] | None = None
        self.restype: Any = None

    def __call__(self, *_args: Any) -> Any:
        return self.result


class _FakeLibrary:
    def __init__(self, version: int = NATIVE_API_VERSION) -> None:
        self.ss_api_version = _FakeFunction(version)
        self.ss_shutdown = _FakeFunction()

    def __getattr__(self, name: str) -> _FakeFunction:
        function = _FakeFunction()
        setattr(self, name, function)
        return function


class _FakeDirectory:
    def close(self) -> None:
        pass


def test_native_bridge_configures_the_complete_abi(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _FakeLibrary()
    dll = tmp_path / "selectspeak_native.dll"
    dll.touch()
    monkeypatch.setattr(native_bindings.ctypes, "CDLL", lambda _path: library)
    monkeypatch.setattr(
        native_bindings.os,
        "add_dll_directory",
        lambda _path: _FakeDirectory(),
        raising=False,
    )

    bridge = NativeBridge(dll)

    assert library.ss_input_start.argtypes is not None
    assert library.ss_ocr_recognize_bgra.argtypes is not None
    assert library.ss_voice_speak.argtypes == [ctypes.c_wchar_p]
    assert library.ss_audio_request_create.restype is ctypes.c_uint32
    assert library.ss_audio_request_destroy.argtypes == [AudioRequestHandle]
    bridge.close()


def test_python_audio_wire_values_and_layout_match_the_frozen_contract() -> None:
    assert NATIVE_API_VERSION == 7
    assert list(NativeStatus) == [
        NativeStatus.OK,
        NativeStatus.INVALID_HANDLE,
        NativeStatus.INVALID_REQUEST,
        NativeStatus.INVALID_ARGUMENT,
        NativeStatus.INVALID_BOUNDARY,
        NativeStatus.WRONG_STATE,
        NativeStatus.DEVICE_ERROR,
        NativeStatus.CLOSED,
        NativeStatus.INTERNAL_ERROR,
    ]
    assert [status.value for status in NativeTerminalStatus] == [
        status.value for status in TerminalStatus
    ]
    assert NativeSampleFormat.PCM_S16_LE == 1
    assert NativeAudioEventKind.TERMINAL == 4
    assert ctypes.sizeof(NativeAudioFormat) == 16
    assert ctypes.sizeof(NativeAudioBoundary) == 16
    assert ctypes.sizeof(NativeAudioSubmitResult) == 24
    assert ctypes.sizeof(NativeAudioEvent) == 48
    assert ctypes.sizeof(NativeNaturalSynthesisResult) == 32


def test_native_status_checker_preserves_unknown_future_codes() -> None:
    check_native_status(NativeStatus.OK, "create audio request")

    with pytest.raises(NativeCallError, match=r"status 6 \(device_error\)") as known:
        check_native_status(NativeStatus.DEVICE_ERROR, "create audio request", "No device")
    assert known.value.status is NativeStatus.DEVICE_ERROR
    assert known.value.status_code == 6

    with pytest.raises(NativeCallError, match=r"status 99 \(unknown\)") as unknown:
        check_native_status(99, "create audio request")
    assert unknown.value.status is None
    assert unknown.value.status_code == 99


@pytest.mark.skipif(
    sys.platform != "win32" or not RUNTIME_NATIVE_DLL.is_file(),
    reason="built Windows native bridge is unavailable",
)
def test_staged_bridge_matches_version_7_audio_abi() -> None:
    bridge = NativeBridge(RUNTIME_NATIVE_DLL)
    events: list[int] = []
    callback = AudioEventCallback(
        lambda event, _context: events.append(event.contents.kind)
    )
    audio_format = NativeAudioFormat(
        ctypes.sizeof(NativeAudioFormat),
        24_000,
        1,
        NativeSampleFormat.PCM_S16_LE,
    )
    handle = AudioRequestHandle(99)

    status = bridge.library.ss_audio_request_create(
        1,
        ctypes.byref(audio_format),
        10,
        callback,
        None,
        ctypes.byref(handle),
    )

    assert status == NativeStatus.DEVICE_ERROR
    assert handle.value == 0
    assert events == []
    assert bridge.library.ss_audio_request_destroy(handle) == NativeStatus.INVALID_HANDLE
    bridge.close()
