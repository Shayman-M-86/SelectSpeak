from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ..speech.normalization import prepare_for_speech

CaptureSource = Literal["selection", "clipboard_fallback", "empty"]


@dataclass(frozen=True, slots=True)
class CaptureResult:
    source: CaptureSource
    raw_text: str
    text: str


def resolve_capture(
    selected_text: str,
    read_clipboard: Callable[[], str | None],
    *,
    allow_clipboard_fallback: bool,
) -> CaptureResult:
    """Prefer selected text and use the clipboard only as an enabled fallback."""
    cleaned_selection = prepare_for_speech(selected_text)
    if cleaned_selection:
        return CaptureResult("selection", selected_text, cleaned_selection)

    if not allow_clipboard_fallback:
        return CaptureResult("empty", selected_text, "")

    clipboard_text = read_clipboard() or ""
    return CaptureResult(
        "clipboard_fallback",
        clipboard_text,
        prepare_for_speech(clipboard_text),
    )
