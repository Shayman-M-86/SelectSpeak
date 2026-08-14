import json
import os
import sys
from pathlib import Path

from selectspeak.speech import optional_dependencies


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
                "layer_version": optional_dependencies.SUPERTONIC_LAYER_VERSION,
                "python_tag": f"cp{sys.version_info.major}{sys.version_info.minor}",
            }
        ),
        encoding="utf-8",
    )


def test_dependency_layer_requires_a_compatible_manifest(tmp_path: Path) -> None:
    _complete_layer(tmp_path)
    assert optional_dependencies.supertonic_dependencies_are_installed(tmp_path)

    manifest = tmp_path / "supertonic-layer.json"
    contents = json.loads(manifest.read_text(encoding="utf-8"))
    contents["python_tag"] = "cp999"
    manifest.write_text(json.dumps(contents), encoding="utf-8")

    assert not optional_dependencies.supertonic_dependencies_are_installed(tmp_path)


def test_activation_adds_package_and_native_library_paths(monkeypatch, tmp_path: Path) -> None:
    _complete_layer(tmp_path)
    (tmp_path / "numpy.libs").mkdir()
    (tmp_path / "onnxruntime" / "capi").mkdir()
    added_dll_directories: list[str] = []
    monkeypatch.setattr(
        optional_dependencies.os,
        "add_dll_directory",
        lambda path: added_dll_directories.append(path) or object(),
        raising=False,
    )
    monkeypatch.setattr(optional_dependencies, "_activated_root", None)
    monkeypatch.setattr(optional_dependencies, "_dll_directory_handles", [])
    monkeypatch.delenv("HF_HUB_DISABLE_XET", raising=False)
    original_path = list(sys.path)
    try:
        assert optional_dependencies.activate_supertonic_dependencies(tmp_path) == tmp_path.resolve()
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
        optional_dependencies.activate_supertonic_dependencies(tmp_path)
    except optional_dependencies.SupertonicDependenciesMissing as error:
        assert "select the Supertonic Neural Voice component" in str(error)
    else:
        raise AssertionError("An incomplete dependency layer was accepted")
