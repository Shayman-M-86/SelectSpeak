from pathlib import Path
from typing import Any

import pytest

from selectspeak.native import (
    NativeBridge,
    NativeBridgeError,
    find_native_dll,
)
from selectspeak.native import bindings as native


def test_find_native_dll_accepts_an_explicit_path(tmp_path: Path) -> None:
    dll = tmp_path / "selectspeak_native.dll"
    dll.touch()

    assert find_native_dll(str(dll)) == dll.resolve()


def test_find_native_dll_reports_build_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SELECTSPEAK_NATIVE_DLL", raising=False)
    monkeypatch.setattr(Path, "is_file", lambda _path: False)

    with pytest.raises(NativeBridgeError, match="build-tools/native/build.ps1"):
        find_native_dll("Z:/not-present/selectspeak_native.dll")


def test_native_bridge_rejects_an_incompatible_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeFunction:
        def __init__(self, result: Any = None) -> None:
            self.result = result

        def __call__(self, *_args: Any) -> Any:
            return self.result

    class FakeLibrary:
        ss_api_version = FakeFunction(99)
        ss_shutdown = FakeFunction()

    class FakeDirectory:
        def close(self) -> None:
            pass

    dll = tmp_path / "selectspeak_native.dll"
    dll.touch()
    monkeypatch.setattr(native.ctypes, "CDLL", lambda _path: FakeLibrary())
    monkeypatch.setattr(
        native.os,
        "add_dll_directory",
        lambda _path: FakeDirectory(),
        raising=False,
    )

    with pytest.raises(NativeBridgeError, match="expected API 3, found 99"):
        NativeBridge(dll)
