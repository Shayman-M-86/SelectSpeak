"""Stable, opaque identity keys for installed Windows Natural Voices."""

from __future__ import annotations

import base64
import json

_PREFIX = "natural:v1:"


def natural_voice_key(package_path: str, sdk_voice_name: str) -> str:
    """Return a persistence-safe key for one exact SDK voice in one package."""
    payload = json.dumps((package_path, sdk_voice_name), ensure_ascii=False, separators=(",", ":"))
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{_PREFIX}{token}"


def parse_natural_voice_key(value: str) -> tuple[str, str] | None:
    """Decode an exact identity key, rejecting legacy and malformed values."""
    if not value.startswith(_PREFIX):
        return None
    try:
        token = value[len(_PREFIX) :]
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not all(isinstance(item, str) and item for item in payload)
    ):
        return None
    return payload[0], payload[1]
