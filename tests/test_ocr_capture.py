import ctypes
import sys
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from PIL import Image, ImageDraw, ImageFont

from selectspeak.input import ocr_capture
from selectspeak.input.ocr_capture import OcrCaptureHotkey

RUNTIME_OCR_DLL = (
    Path(__file__).parents[1]
    / ".runtime"
    / "input"
    / "selectspeak_input.dll"
)


class _FakeFunction:
    def __init__(self, implementation: Any) -> None:
        self.implementation = implementation

    def __call__(self, *args: Any) -> Any:
        return self.implementation(*args)


class _FakeOcrDll:
    def __init__(self) -> None:
        self.callback: Any = None
        self.start_args: tuple[Any, ...] = ()
        self.stopped = False
        self.ocr_start = _FakeFunction(self._start)
        self.ocr_cancel = _FakeFunction(lambda: None)
        self.ocr_is_active = _FakeFunction(lambda: 1)
        self.ocr_stop = _FakeFunction(self._stop)
        self.ocr_last_error = _FakeFunction(lambda _buffer, _length: 1)

    def _start(self, *args: Any) -> int:
        self.start_args = args
        self.callback = args[3]
        return 0

    def _stop(self) -> None:
        self.stopped = True


def _adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    on_text: Any,
) -> tuple[OcrCaptureHotkey, _FakeOcrDll]:
    dll = _FakeOcrDll()
    monkeypatch.setattr(
        ocr_capture,
        "find_native_input_dll",
        lambda _configured: tmp_path / "selectspeak_input.dll",
    )
    monkeypatch.setattr(ocr_capture.ctypes, "CDLL", lambda _path: dll)
    return OcrCaptureHotkey("alt+d", on_text, language="en-AU"), dll


def test_native_ocr_registers_hotkey_and_returns_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    completed = Event()
    captured: list[str] = []
    adapter, dll = _adapter(
        monkeypatch,
        tmp_path,
        lambda text: (captured.append(text), completed.set()),
    )

    adapter.start()
    dll.callback("Recognized directly", 1, None)

    assert completed.wait(1.0)
    assert captured == ["Recognized directly"]
    assert dll.start_args[:3] == (0x0001, ord("D"), "en-AU")
    assert adapter.active


def test_native_ocr_ignores_cancelled_and_empty_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[str] = []
    adapter, dll = _adapter(monkeypatch, tmp_path, captured.append)
    adapter.start()

    dll.callback(None, 2, None)
    dll.callback("  ", 1, None)
    adapter.stop()

    assert captured == []
    assert dll.stopped


@pytest.mark.skipif(
    sys.platform != "win32" or not RUNTIME_OCR_DLL.is_file(),
    reason="built Windows input bridge is unavailable",
)
def test_built_bridge_recognizes_generated_text_without_clipboard() -> None:
    callback_type = ctypes.CFUNCTYPE(
        None,
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_void_p,
    )
    results: list[tuple[int, str]] = []
    callback = callback_type(
        lambda text, status, _context: results.append((status, text or ""))
    )
    dll = ctypes.CDLL(str(RUNTIME_OCR_DLL))
    dll.ocr_recognize_bgra.argtypes = [
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        callback_type,
        ctypes.c_void_p,
    ]
    dll.ocr_recognize_bgra.restype = ctypes.c_int

    image = Image.new("RGBA", (1200, 220), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 72)
    draw.text(
        (30, 55),
        "SelectSpeak native OCR works",
        fill="black",
        font=font,
    )
    bgra = image.tobytes("raw", "BGRA")
    pixels = (ctypes.c_ubyte * len(bgra)).from_buffer_copy(bgra)

    return_code = dll.ocr_recognize_bgra(
        pixels,
        image.width,
        image.height,
        image.width * 4,
        "en-US",
        callback,
        None,
    )

    assert return_code == 0
    assert results == [(1, "SelectSpeak native OCR works")]
