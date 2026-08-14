"""Python bindings for the SelectSpeak-owned native bridge."""

from .bindings import (
    NATIVE_API_VERSION,
    NativeBridge,
    NativeBridgeError,
    find_native_dll,
    get_native_bridge,
    shutdown_native_bridge,
)

__all__ = [
    "NATIVE_API_VERSION",
    "NativeBridge",
    "NativeBridgeError",
    "find_native_dll",
    "get_native_bridge",
    "shutdown_native_bridge",
]
