from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from ..runtime_paths import app_dir, is_frozen

SUPERTONIC_LAYER_VERSION = "1"
SUPERTONIC_LAYER_DIRECTORY = "supertonic"
_MANIFEST_NAME = "supertonic-layer.json"
_REQUIRED_PATHS = (
    Path("supertonic/__init__.py"),
    Path("numpy/__init__.py"),
    Path("onnxruntime/__init__.py"),
)
_dll_directory_handles: list[Any] = []
_activated_root: Path | None = None


class SupertonicDependenciesMissing(RuntimeError):
    """Raised when the optional neural dependency layer is unavailable."""


def supertonic_dependency_dir() -> Path:
    override = os.environ.get("SELECTSPEAK_SUPERTONIC_DEPENDENCIES")
    if override:
        return Path(override).expanduser().resolve()
    return app_dir() / "dependencies" / SUPERTONIC_LAYER_DIRECTORY


def supertonic_dependencies_are_installed(root: Path | None = None) -> bool:
    """Return whether a compatible, complete optional dependency layer exists."""
    if not is_frozen() and root is None and not os.environ.get("SELECTSPEAK_SUPERTONIC_DEPENDENCIES"):
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
            import supertonic  # noqa: F401
        except ImportError:
            return False
        return True

    dependency_root = root or supertonic_dependency_dir()
    try:
        manifest = json.loads((dependency_root / _MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    expected_python = f"cp{sys.version_info.major}{sys.version_info.minor}"
    return (
        manifest.get("schema_version") == 1
        and manifest.get("layer_version") == SUPERTONIC_LAYER_VERSION
        and manifest.get("python_tag") == expected_python
        and all((dependency_root / relative).is_file() for relative in _REQUIRED_PATHS)
    )


def activate_supertonic_dependencies(root: Path | None = None) -> Path:
    """Make the installed neural dependency layer importable in this process."""
    global _activated_root

    dependency_root = (root or supertonic_dependency_dir()).resolve()
    if _activated_root == dependency_root:
        return dependency_root
    if not supertonic_dependencies_are_installed(dependency_root):
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
