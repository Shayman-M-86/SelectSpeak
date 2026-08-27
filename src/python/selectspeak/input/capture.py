from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

CaptureSource = Literal["selection", "clipboard_fallback", "empty"]


@dataclass(frozen=True, slots=True)
class CaptureResult:
    source: CaptureSource
    raw_text: str


def resolve_capture(
    selected_text: str,
    read_clipboard: Callable[[], str | None],
    *,
    allow_clipboard_fallback: bool,
) -> CaptureResult:
    """Prefer selected text and use the clipboard only as an enabled fallback."""
    if selected_text.strip():
        return CaptureResult("selection", selected_text)

    if not allow_clipboard_fallback:
        return CaptureResult("empty", selected_text)

    return CaptureResult("clipboard_fallback", read_clipboard() or "")
