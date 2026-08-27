from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

CaptureSource = Literal["selection", "clipboard_fallback", "empty", "unresolved"]


@dataclass(frozen=True, slots=True)
class CaptureResult:
    source: CaptureSource
    raw_text: str


def resolve_capture(
    selected_text: str,
    read_clipboard: Callable[[], str | None],
    *,
    allow_clipboard_fallback: bool,
    capture_unresolved: bool = False,
) -> CaptureResult:
    """Prefer selected text and use the clipboard only as an enabled fallback.

    capture_unresolved means the native layer sent a copy action but never
    saw the clipboard change before its timeout. The target may still finish
    the copy later, so this must not be treated as "nothing selected" -
    reading the clipboard now could pick up stale or racing content.
    """
    if selected_text.strip():
        return CaptureResult("selection", selected_text)

    if capture_unresolved:
        return CaptureResult("unresolved", "")

    if not allow_clipboard_fallback:
        return CaptureResult("empty", selected_text)

    return CaptureResult("clipboard_fallback", read_clipboard() or "")
