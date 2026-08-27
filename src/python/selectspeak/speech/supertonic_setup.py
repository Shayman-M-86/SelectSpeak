"""Everything about the optional Supertonic component in one place.

Supertonic is the one optional, installable speech backend SelectSpeak has, so
its dependency-layer activation, model/voice readiness, and installer
acquisition live together here rather than split across separate modules.
This is deliberately a plain module of functions, not a generic plugin
framework — Supertonic is the only optional component and is expected to stay
that way.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import __version__
from ..config.paths import app_dir, is_frozen, model_dir

if os.name == "nt":
    import winreg
else:
    winreg = None  # type: ignore[assignment]

_REPOSITORY = "Shayman-M-86/my-TTS"
_HASH_PATTERN = re.compile(r"\b([0-9a-fA-F]{64})\b")

# -- dependency-layer activation --------------------------------------------

SUPERTONIC_LAYER_VERSION = "1"
SUPERTONIC_LAYER_DIRECTORY = "supertonic"
_MANIFEST_NAME = "supertonic-layer.json"
_REQUIRED_DEPENDENCY_PATHS = (
    Path("supertonic/__init__.py"),
    Path("numpy/__init__.py"),
    Path("onnxruntime/__init__.py"),
)
_dll_directory_handles: list[Any] = []
_activated_root: Path | None = None


class SupertonicDependenciesMissing(RuntimeError):
    """Raised when the optional neural dependency layer is unavailable."""


def dependency_dir() -> Path:
    override = os.environ.get("SELECTSPEAK_SUPERTONIC_DEPENDENCIES")
    if override:
        return Path(override).expanduser().resolve()
    return app_dir() / "dependencies" / SUPERTONIC_LAYER_DIRECTORY


def dependencies_installed(root: Path | None = None) -> bool:
    """Return whether a compatible, complete optional dependency layer exists."""
    dependency_root = root or dependency_dir()
    try:
        manifest = json.loads((dependency_root / _MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    expected_python = f"cp{sys.version_info.major}{sys.version_info.minor}"
    return (
        manifest.get("schema_version") == 1
        and manifest.get("layer_version") == SUPERTONIC_LAYER_VERSION
        and manifest.get("python_tag") == expected_python
        and all((dependency_root / relative).is_file() for relative in _REQUIRED_DEPENDENCY_PATHS)
    )


def activate_dependencies(root: Path | None = None) -> Path:
    """Make the installed neural dependency layer importable in this process."""
    global _activated_root

    dependency_root = (root or dependency_dir()).resolve()
    if _activated_root == dependency_root:
        return dependency_root
    if not dependencies_installed(dependency_root):
        raise SupertonicDependenciesMissing(
            "Supertonic support is not installed. Run SelectSpeak Setup and select "
            "the Supertonic Neural Voice component."
        )

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    dependency_path = str(dependency_root)
    if dependency_path not in sys.path:
        sys.path.insert(0, dependency_path)

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        for directory in (
            dependency_root,
            dependency_root / "numpy.libs",
            dependency_root / "onnxruntime" / "capi",
        ):
            if directory.is_dir():
                _dll_directory_handles.append(add_dll_directory(str(directory)))
    _activated_root = dependency_root
    return dependency_root


# -- model and voice readiness -----------------------------------------------

_REQUIRED_MODEL_FILES = (
    Path("onnx/tts.json"),
    Path("onnx/unicode_indexer.json"),
    Path("onnx/duration_predictor.onnx"),
    Path("onnx/text_encoder.onnx"),
    Path("onnx/vector_estimator.onnx"),
    Path("onnx/vocoder.onnx"),
)
DEFAULT_SUPERTONIC_VOICES = tuple(f"{family}{index}" for family in ("F", "M") for index in range(1, 6))


def available_voices(root: Path | None = None) -> tuple[str, ...]:
    """List usable local Supertonic styles, with stable pre-install choices."""
    model_root = root or model_dir("supertonic3")
    styles_directory = model_root / "voice_styles"
    styles = sorted(
        (path.stem for path in styles_directory.glob("*.json") if path.is_file()),
        key=str.casefold,
    )
    return tuple(styles) if styles else DEFAULT_SUPERTONIC_VOICES


def model_installed(voice: str, root: Path | None = None) -> bool:
    """Return whether the local model and selected voice style are complete."""
    model_root = root or model_dir("supertonic3")
    required = (*_REQUIRED_MODEL_FILES, Path("voice_styles") / f"{voice}.json")
    return all((model_root / relative).is_file() for relative in required)


def is_ready(voice: str) -> bool:
    """Return whether Supertonic can be used for the given voice right now."""
    return dependencies_installed() and model_installed(voice)


# -- installer acquisition and launch ----------------------------------------


def installer_url(version: str = __version__) -> str:
    filename = f"SelectSpeak-Setup-{version}.exe"
    return f"https://github.com/{_REPOSITORY}/releases/download/v{version}/{filename}"


def acquire_installer(version: str = __version__) -> Path:
    """Return a verified setup executable suitable for component maintenance."""
    override = os.environ.get("SELECTSPEAK_INSTALLER_PATH")
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"SelectSpeak installer not found: {path}")
        return path

    filename = f"SelectSpeak-Setup-{version}.exe"
    for candidate in _local_installer_candidates(filename):
        if candidate.is_file():
            return candidate.resolve()

    url = installer_url(version)
    destination = Path(tempfile.gettempdir()) / filename
    try:
        expected_hash = _download_release_hash(f"{url}.sha256")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise RuntimeError(
                f"SelectSpeak {version} has not been published yet and the original "
                "installer could not be found. Run the installer from the dist folder "
                "and select Supertonic Neural Voice."
            ) from error
        raise
    if destination.is_file() and _sha256(destination) == expected_hash:
        return destination

    partial = destination.with_suffix(".exe.download")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if _sha256(partial) != expected_hash:
            raise RuntimeError("The downloaded SelectSpeak installer failed SHA-256 verification.")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def launch_installer(installer: Path | None = None) -> subprocess.Popen[bytes]:
    """Open setup with the optional Supertonic component preselected."""
    setup = installer or acquire_installer()
    return subprocess.Popen([str(setup), "/COMPONENTS=supertonic"])


def _download_release_hash(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        contents = response.read(4096).decode("ascii", errors="strict")
    match = _HASH_PATTERN.search(contents)
    if match is None:
        raise RuntimeError("The SelectSpeak release checksum is invalid.")
    return match.group(1).casefold()


def _local_installer_candidates(filename: str) -> tuple[Path, ...]:
    candidates: list[Path] = []
    registered = _registered_installer_path()
    if registered is not None and registered.name.casefold() == filename.casefold():
        candidates.append(registered)
    root = app_dir()
    candidates.append(root / filename)
    if not is_frozen():
        candidates.append(root / "dist" / filename)
    return tuple(candidates)


def _registered_installer_path() -> Path | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SelectSpeak") as key:
            value, _kind = winreg.QueryValueEx(key, "InstallerPath")
    except OSError:
        return None
    return Path(str(value)).expanduser()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
