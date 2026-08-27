from __future__ import annotations

import ctypes
from enum import IntEnum
from typing import Any, Final

NATIVE_API_VERSION: Final = 8


class NativeStatus(IntEnum):
    OK = 0
    INVALID_HANDLE = 1
    INVALID_REQUEST = 2
    INVALID_ARGUMENT = 3
    INVALID_BOUNDARY = 4
    WRONG_STATE = 5
    DEVICE_ERROR = 6
    CLOSED = 7
    INTERNAL_ERROR = 8


class NativeCallError(RuntimeError):
    def __init__(self, action: str, status_code: int, diagnostic: str = "") -> None:
        self.status_code = int(status_code)
        try:
            self.status: NativeStatus | None = NativeStatus(self.status_code)
        except ValueError:
            self.status = None
        status_name = self.status.name.lower() if self.status is not None else "unknown"
        detail = f": {diagnostic}" if diagnostic else ""
        super().__init__(f"Could not {action}: native status {self.status_code} ({status_name}){detail}")


def check_native_status(status_code: int, action: str, diagnostic: str = "") -> None:
    if status_code != NativeStatus.OK:
        raise NativeCallError(action, status_code, diagnostic)


class NativeSampleFormat(IntEnum):
    PCM_S16_LE = 1


class NativeAudioEventKind(IntEnum):
    STARTED = 1
    PLAYED_WORD = 2
    UNDERRUN = 3
    TERMINAL = 4


class NativeTerminalStatus(IntEnum):
    NONE = 0
    COMPLETED = 1
    CANCELLED = 2
    SUPERSEDED = 3
    FAILED = 4
    CLOSED = 5


class NativeAudioFormat(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("sample_rate_hz", ctypes.c_uint32),
        ("channel_count", ctypes.c_uint32),
        ("sample_format", ctypes.c_uint32),
    ]


class NativeAudioBoundary(ctypes.Structure):
    _fields_ = [
        ("frame_offset", ctypes.c_uint64),
        ("text_position", ctypes.c_uint32),
        ("text_length", ctypes.c_uint32),
    ]


class NativeAudioSubmitResult(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("accepted_frames", ctypes.c_uint64),
        ("buffered_frames_after_submit", ctypes.c_uint64),
    ]


class NativeAudioEvent(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("kind", ctypes.c_uint32),
        ("request_id", ctypes.c_uint64),
        ("terminal_status", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("text_position", ctypes.c_uint32),
        ("text_length", ctypes.c_uint32),
        ("buffered_frames", ctypes.c_uint64),
        ("diagnostic", ctypes.c_char_p),
    ]


class NativeNaturalSynthesisResult(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("generated_frames", ctypes.c_uint64),
        ("synthesis_duration_us", ctypes.c_uint64),
        ("buffered_frames_after_submit", ctypes.c_uint64),
    ]


CaptureCallback = ctypes.CFUNCTYPE(None, ctypes.c_wchar_p, ctypes.c_void_p)
ActivationCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
OcrCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.c_wchar_p,
    ctypes.c_uint32,
    ctypes.c_void_p,
)
VoiceAudioCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(ctypes.c_uint8),
    ctypes.c_uint32,
    ctypes.c_void_p,
)
VoiceWordCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.c_uint64,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_void_p,
)
VoiceListCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.c_wchar_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
)
AudioEventCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(NativeAudioEvent),
    ctypes.c_void_p,
)

AudioRequestHandle = ctypes.c_uint64


def configure_native_bootstrap(library: Any) -> None:
    """Configure the stable symbols needed to reject an old DLL cleanly."""
    _declare(library, "ss_api_version", [], ctypes.c_uint32)
    _declare(library, "ss_shutdown", [], None)


def configure_native_library(library: Any) -> None:
    """Configure the complete versioned SelectSpeak C ABI exactly once per DLL."""
    _declare(library, "ss_api_version", [], ctypes.c_uint32)
    _declare(library, "ss_shutdown", [], None)

    _declare(
        library,
        "ss_input_start",
        [
            ctypes.c_uint32,
            ctypes.c_uint32,
            CaptureCallback,
            ActivationCallback,
            ctypes.c_void_p,
        ],
        ctypes.c_int,
    )
    _declare(
        library,
        "ss_input_rebind",
        [ctypes.c_uint32, ctypes.c_uint32],
        ctypes.c_int,
    )
    _declare(library, "ss_input_capture_now", [], ctypes.c_int)
    _declare(library, "ss_input_stop", [], None)
    _declare(library, "ss_input_last_capture_source", [], ctypes.c_uint32)
    _declare(library, "ss_input_last_activation_time_ms", [], ctypes.c_uint64)
    _declare(
        library,
        "ss_input_last_capture_trace",
        [ctypes.c_char_p, ctypes.c_uint32],
        ctypes.c_uint32,
    )
    _declare(
        library,
        "ss_input_last_clipboard_fallback",
        [ctypes.c_wchar_p, ctypes.c_uint32],
        ctypes.c_uint32,
    )
    _declare(
        library,
        "ss_input_last_error",
        [ctypes.c_char_p, ctypes.c_uint32],
        ctypes.c_uint32,
    )

    _declare(
        library,
        "ss_ocr_start",
        [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_wchar_p,
            OcrCallback,
            ctypes.c_void_p,
        ],
        ctypes.c_int,
    )
    _declare(library, "ss_ocr_cancel", [], None)
    _declare(library, "ss_ocr_is_active", [], ctypes.c_int)
    _declare(library, "ss_ocr_stop", [], None)
    _declare(
        library,
        "ss_ocr_last_error",
        [ctypes.c_char_p, ctypes.c_uint32],
        ctypes.c_uint32,
    )
    _declare(
        library,
        "ss_ocr_recognize_bgra",
        [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_uint64,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_wchar_p,
            OcrCallback,
            ctypes.c_void_p,
        ],
        ctypes.c_int,
    )

    _declare(
        library,
        "ss_voice_list",
        [VoiceListCallback, ctypes.c_void_p],
        ctypes.c_uint32,
    )
    _declare(
        library,
        "ss_voice_initialize",
        [ctypes.c_wchar_p, ctypes.c_char_p],
        ctypes.c_int,
    )
    _declare(
        library,
        "ss_voice_set_audio_callback",
        [VoiceAudioCallback, ctypes.c_void_p],
        None,
    )
    _declare(
        library,
        "ss_voice_set_word_callback",
        [VoiceWordCallback, ctypes.c_void_p],
        None,
    )
    _declare(library, "ss_voice_speak", [ctypes.c_wchar_p], ctypes.c_int)
    _declare(library, "ss_voice_set_volume", [ctypes.c_uint32], ctypes.c_uint32)
    _declare(
        library,
        "ss_voice_synthesize_to_audio",
        [
            AudioRequestHandle,
            ctypes.c_uint64,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.POINTER(NativeNaturalSynthesisResult),
        ],
        ctypes.c_uint32,
    )
    _declare(library, "ss_voice_stop", [], ctypes.c_int)
    _declare(library, "ss_voice_shutdown", [], None)
    _declare(
        library,
        "ss_voice_last_error",
        [ctypes.c_char_p, ctypes.c_uint32],
        ctypes.c_uint32,
    )

    _declare(
        library,
        "ss_audio_request_create",
        [
            ctypes.c_uint64,
            ctypes.POINTER(NativeAudioFormat),
            ctypes.c_uint32,
            AudioEventCallback,
            ctypes.c_void_p,
            ctypes.POINTER(AudioRequestHandle),
        ],
        ctypes.c_uint32,
    )
    _declare(
        library,
        "ss_audio_request_submit",
        [
            AudioRequestHandle,
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(NativeAudioBoundary),
            ctypes.c_uint32,
            ctypes.POINTER(NativeAudioSubmitResult),
        ],
        ctypes.c_uint32,
    )
    _declare(library, "ss_audio_request_finish_input", [AudioRequestHandle], ctypes.c_uint32)
    _declare(library, "ss_audio_request_pause", [AudioRequestHandle], ctypes.c_uint32)
    _declare(library, "ss_audio_request_resume", [AudioRequestHandle], ctypes.c_uint32)
    _declare(
        library,
        "ss_audio_request_stop",
        [AudioRequestHandle, ctypes.c_uint32],
        ctypes.c_uint32,
    )
    _declare(library, "ss_audio_request_destroy", [AudioRequestHandle], ctypes.c_uint32)


def _declare(library: Any, name: str, argtypes: list[Any], restype: Any) -> None:
    function = getattr(library, name)
    function.argtypes = argtypes
    function.restype = restype
