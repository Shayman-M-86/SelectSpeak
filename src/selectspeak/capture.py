import logging

from .logging_setup import log_event, text_preview

logger = logging.getLogger(__name__)


def fresh_clipboard_text(original: str | None, candidate: str | None) -> str | None:
    """Accept copied text only when it differs from the pre-copy clipboard.

    A same-value copy is ambiguous: it may be a legitimate identical selection,
    but it may also be stale clipboard data after a failed synthetic Ctrl+C.
    Refusing to speak is safer than reading unrelated stale content.
    """
    accepted = bool(candidate) and candidate != original
    log_event(
        logger,
        logging.DEBUG,
        "capture.candidate.evaluated",
        original_length=len(original) if original is not None else None,
        candidate_length=len(candidate) if candidate is not None else None,
        original_preview=text_preview(original),
        candidate_preview=text_preview(candidate),
        accepted=accepted,
    )
    if not accepted:
        return None
    return candidate
