import logging
import re

from .logging_setup import log_event, text_preview

logger = logging.getLogger(__name__)


def tidy_text(text: str) -> str:
    """Collapse whitespace so SAPI reads copied text naturally."""
    stripped = text.strip()
    single_line = stripped.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    result = re.sub(r"\s{2,}", " ", single_line).strip()
    log_event(
        logger,
        logging.DEBUG,
        "text.tidied",
        input_length=len(text),
        output_length=len(result),
        input_preview=text_preview(text),
        output_preview=text_preview(result),
    )
    return result
