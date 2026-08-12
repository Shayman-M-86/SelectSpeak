from pathlib import Path

import pytest

from selectspeak.input.native import NativeInputError, find_native_input_dll


def test_find_native_input_dll_accepts_an_explicit_path(tmp_path: Path) -> None:
    dll = tmp_path / "selectspeak_input.dll"
    dll.touch()

    assert find_native_input_dll(str(dll)) == dll.resolve()


def test_find_native_input_dll_reports_build_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SELECTSPEAK_INPUT_DLL", raising=False)
    monkeypatch.setattr(Path, "is_file", lambda _path: False)

    with pytest.raises(NativeInputError, match="build native/input"):
        find_native_input_dll("Z:/not-present/selectspeak_input.dll")
