from pathlib import Path

from selectspeak.config import paths as runtime_paths


def test_development_app_directory_is_the_repository_root() -> None:
    assert runtime_paths.app_dir() == Path(__file__).resolve().parents[1]


def test_user_paths_live_under_local_app_data(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("SELECTSPEAK_USER_DATA_DIR", raising=False)

    assert runtime_paths.user_data_dir() == tmp_path / "SelectSpeak"
    assert runtime_paths.log_dir() == tmp_path / "SelectSpeak" / "logs"
    assert runtime_paths.model_dir() == tmp_path / "SelectSpeak" / "models" / "supertonic3"
    assert runtime_paths.settings_path() == tmp_path / "SelectSpeak" / "settings.json"


def test_frozen_native_runtime_is_beside_the_executable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "SelectSpeak.exe"
    monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_paths.sys, "executable", str(executable))

    assert runtime_paths.app_dir() == tmp_path
    assert runtime_paths.native_dir() == tmp_path / "native"
    assert runtime_paths.licenses_dir() == tmp_path / "licenses"


def test_user_data_override_is_supported(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "portable-data"
    monkeypatch.setenv("SELECTSPEAK_USER_DATA_DIR", str(target))

    assert runtime_paths.user_data_dir() == target.resolve()
