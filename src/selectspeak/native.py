from __future__ import annotations

import atexit
import ctypes
import os
import threading
from pathlib import Path
from typing import Any

from .runtime_paths import repository_runtime_path

NATIVE_API_VERSION = 1


class NativeBridgeError(RuntimeError):
    pass


def find_native_dll(configured_path: str = "") -> Path:
    candidates = (
        configured_path,
        os.environ.get("SELECTSPEAK_NATIVE_DLL", ""),
        str(repository_runtime_path("native", "selectspeak_native.dll")),
        str(Path(__file__).with_name("selectspeak_native.dll")),
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise NativeBridgeError(
        "SelectSpeak native bridge not found; run native/build.ps1 or set "
        "SELECTSPEAK_NATIVE_DLL"
    )


class NativeBridge:
    """Load and own the single versioned native library for this process."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._closed = False
        self._dll_directory: Any = None
        if hasattr(os, "add_dll_directory"):
            self._dll_directory = os.add_dll_directory(str(path.parent))
        try:
            self.library = ctypes.CDLL(str(path))
            self.library.ss_api_version.argtypes = []
            self.library.ss_api_version.restype = ctypes.c_uint32
            self.library.ss_shutdown.argtypes = []
            self.library.ss_shutdown.restype = None
            actual_version = self.library.ss_api_version()
            if actual_version != NATIVE_API_VERSION:
                raise NativeBridgeError(
                    "Incompatible SelectSpeak native bridge: expected API "
                    f"{NATIVE_API_VERSION}, found {actual_version} at {path}"
                )
        except Exception:
            if self._dll_directory is not None:
                self._dll_directory.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self.library.ss_shutdown()
        self._closed = True
        if self._dll_directory is not None:
            self._dll_directory.close()


_bridges: dict[Path, NativeBridge] = {}
_bridge_lock = threading.RLock()


def get_native_bridge(configured_path: str = "") -> NativeBridge:
    path = find_native_dll(configured_path)
    with _bridge_lock:
        bridge = _bridges.get(path)
        if bridge is None or bridge._closed:
            bridge = NativeBridge(path)
            _bridges[path] = bridge
        return bridge


def shutdown_native_bridge() -> None:
    with _bridge_lock:
        bridges = list(_bridges.values())
        _bridges.clear()
    for bridge in bridges:
        bridge.close()


atexit.register(shutdown_native_bridge)
