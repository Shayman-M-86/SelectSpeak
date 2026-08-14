from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .. import __version__
from ..config.paths import app_dir, is_frozen

_REPOSITORY = "Shayman-M-86/my-TTS"
_HASH_PATTERN = re.compile(r"\b([0-9a-fA-F]{64})\b")


def supertonic_installer_url(version: str = __version__) -> str:
    filename = f"SelectSpeak-Setup-{version}.exe"
    return f"https://github.com/{_REPOSITORY}/releases/download/v{version}/{filename}"


def acquire_feature_installer(version: str = __version__) -> Path:
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

    url = supertonic_installer_url(version)
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


def launch_supertonic_installer(installer: Path | None = None) -> subprocess.Popen[bytes]:
    """Open setup with the optional Supertonic component preselected."""
    setup = installer or acquire_feature_installer()
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
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SelectSpeak") as key:
            value, _kind = winreg.QueryValueEx(key, "InstallerPath")
    except (ImportError, OSError):
        return None
    return Path(str(value)).expanduser()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
