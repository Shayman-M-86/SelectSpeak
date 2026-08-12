from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ..speech.normalization import prepare_for_speech

CaptureSource = Literal["selection", "clipboard", "clipboard_fallback"]


@dataclass(frozen=True, slots=True)
class CaptureResult:
    source: CaptureSource
    raw_text: str
    text: str


def resolve_capture(
    selected_text: str,
    read_clipboard: Callable[[], str | None],
    *,
    force_clipboard: bool,
) -> CaptureResult:
    """Prefer meaningful selected text, otherwise fall back to the clipboard."""
    if not force_clipboard:
        cleaned_selection = prepare_for_speech(selected_text)
        if cleaned_selection:
            return CaptureResult("selection", selected_text, cleaned_selection)

    clipboard_text = read_clipboard() or ""
    source: CaptureSource = "clipboard" if force_clipboard else "clipboard_fallback"
    return CaptureResult(source, clipboard_text, prepare_for_speech(clipboard_text))
