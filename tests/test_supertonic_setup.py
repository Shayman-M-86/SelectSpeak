import json
import os
import sys
from pathlib import Path

from selectspeak.speech import supertonic_setup


def _complete_layer(root: Path) -> None:
    for relative in (
        "supertonic/__init__.py",
        "numpy/__init__.py",
        "onnxruntime/__init__.py",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (root / "supertonic-layer.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layer_version": supertonic_setup.SUPERTONIC_LAYER_VERSION,
                "python_tag": f"cp{sys.version_info.major}{sys.version_info.minor}",
            }
        ),
        encoding="utf-8",
    )


def test_dependency_layer_requires_a_compatible_manifest(tmp_path: Path) -> None:
    _complete_layer(tmp_path)
    assert supertonic_setup.dependencies_installed(tmp_path)

    manifest = tmp_path / "supertonic-layer.json"
    contents = json.loads(manifest.read_text(encoding="utf-8"))
    contents["python_tag"] = "cp999"
    manifest.write_text(json.dumps(contents), encoding="utf-8")

    assert not supertonic_setup.dependencies_installed(tmp_path)


def test_activation_adds_package_and_native_library_paths(monkeypatch, tmp_path: Path) -> None:
    _complete_layer(tmp_path)
    (tmp_path / "numpy.libs").mkdir()
    (tmp_path / "onnxruntime" / "capi").mkdir()
    added_dll_directories: list[str] = []
    monkeypatch.setattr(
        supertonic_setup.os,
        "add_dll_directory",
        lambda path: added_dll_directories.append(path) or object(),
        raising=False,
    )
    monkeypatch.setattr(supertonic_setup, "_activated_root", None)
    monkeypatch.setattr(supertonic_setup, "_dll_directory_handles", [])
    monkeypatch.delenv("HF_HUB_DISABLE_XET", raising=False)
    original_path = list(sys.path)
    try:
        assert supertonic_setup.activate_dependencies(tmp_path) == tmp_path.resolve()
        assert sys.path[0] == str(tmp_path.resolve())
        assert os.environ["HF_HUB_DISABLE_XET"] == "1"
        assert added_dll_directories == [
            str(tmp_path.resolve()),
            str((tmp_path / "numpy.libs").resolve()),
            str((tmp_path / "onnxruntime" / "capi").resolve()),
        ]
    finally:
        sys.path[:] = original_path


def test_missing_dependency_layer_raises_actionable_error(tmp_path: Path) -> None:
    try:
        supertonic_setup.activate_dependencies(tmp_path)
    except supertonic_setup.SupertonicDependenciesMissing as error:
        assert "select the Supertonic Neural Voice component" in str(error)
    else:
        raise AssertionError("An incomplete dependency layer was accepted")


def test_application_imports_without_the_supertonic_dependency_layer() -> None:
    """Startup must not need numpy or supertonic.

    Those ship in the optional dependency layer that activate_dependencies()
    puts on sys.path at runtime, so they are absent in a fresh install until
    the user adds the Supertonic component. Importing either at module scope
    crashes the packaged application before it starts, which is invisible in a
    development environment that has both installed.
    """
    import builtins

    optional = {"numpy", "onnxruntime", "supertonic"}
    for name in list(sys.modules):
        if name.split(".")[0] in optional:
            del sys.modules[name]
    for name in list(sys.modules):
        if name.startswith("selectspeak"):
            del sys.modules[name]

    real_import = builtins.__import__

    def without_optional_layer(name: str, *args: object, **kwargs: object) -> object:
        if name.split(".")[0] in optional:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    builtins.__import__ = without_optional_layer
    try:
        import selectspeak.app  # noqa: F401
        import selectspeak.speech.factory  # noqa: F401
    finally:
        builtins.__import__ = real_import
        for name in list(sys.modules):
            if name.startswith("selectspeak"):
                del sys.modules[name]


def test_supertonic_model_requires_engine_files_and_selected_voice(tmp_path: Path) -> None:
    required = (
        "onnx/tts.json",
        "onnx/unicode_indexer.json",
        "onnx/duration_predictor.onnx",
        "onnx/text_encoder.onnx",
        "onnx/vector_estimator.onnx",
        "onnx/vocoder.onnx",
        "voice_styles/F4.json",
    )
    for relative in required:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    assert supertonic_setup.model_installed("F4", tmp_path)
    assert not supertonic_setup.model_installed("M1", tmp_path)


def test_incomplete_supertonic_download_is_not_reported_as_installed(tmp_path: Path) -> None:
    partial_model = tmp_path / "onnx/duration_predictor.onnx"
    partial_model.parent.mkdir(parents=True)
    partial_model.touch()

    assert not supertonic_setup.model_installed("F4", tmp_path)


def test_available_supertonic_voices_uses_installed_styles_or_stable_defaults(tmp_path: Path) -> None:
    assert supertonic_setup.available_voices(tmp_path) == (
        "F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"
    )
    styles = tmp_path / "voice_styles"
    styles.mkdir()
    (styles / "M2.json").write_text("{}", encoding="utf-8")
    (styles / "F4.json").write_text("{}", encoding="utf-8")

    assert supertonic_setup.available_voices(tmp_path) == ("F4", "M2")


def test_release_url_targets_the_matching_setup_version() -> None:
    assert supertonic_setup.installer_url("2.3.4").endswith(
        "/releases/download/v2.3.4/SelectSpeak-Setup-2.3.4.exe"
    )


def test_local_installer_override_is_used(monkeypatch, tmp_path: Path) -> None:
    installer = tmp_path / "SelectSpeak-Setup.exe"
    installer.touch()
    monkeypatch.setenv("SELECTSPEAK_INSTALLER_PATH", str(installer))

    assert supertonic_setup.acquire_installer() == installer.resolve()


def test_developer_build_uses_installer_from_dist(monkeypatch, tmp_path: Path) -> None:
    installer = tmp_path / "dist" / "SelectSpeak-Setup-2.3.4.exe"
    installer.parent.mkdir()
    installer.touch()
    monkeypatch.delenv("SELECTSPEAK_INSTALLER_PATH", raising=False)
    monkeypatch.setattr(supertonic_setup, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(supertonic_setup, "is_frozen", lambda: False)
    monkeypatch.setattr(supertonic_setup, "_registered_installer_path", lambda: None)

    assert supertonic_setup.acquire_installer("2.3.4") == installer.resolve()


def test_installer_launch_preselects_supertonic(monkeypatch, tmp_path: Path) -> None:
    installer = tmp_path / "SelectSpeak-Setup.exe"
    installer.touch()
    calls: list[list[str]] = []

    def fake_popen(arguments: list[str]):
        calls.append(arguments)
        return object()

    monkeypatch.setattr(supertonic_setup.subprocess, "Popen", fake_popen)
    supertonic_setup.launch_installer(installer)

    assert calls == [[str(installer), "/COMPONENTS=supertonic"]]
