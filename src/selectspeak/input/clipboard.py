import logging
import time

import win32clipboard
import win32con

from ..logging_setup import text_preview

logger = logging.getLogger(__name__)


class ClipboardService:
    def __init__(self) -> None:
        logger.debug("clipboard.service.created")

    @staticmethod
    def _open(retries: int = 5, delay: float = 0.05) -> bool:
        for attempt in range(1, retries + 1):
            try:
                win32clipboard.OpenClipboard()
                logger.debug("clipboard.opened attempt=%s", attempt)
                return True
            except Exception:
                logger.debug("clipboard.open.retry attempt=%s retries=%s", attempt, retries)
                time.sleep(delay)
        logger.warning("clipboard.open.failed retries=%s", retries)
        return False

    def read_text(self) -> str | None:
        logger.debug("clipboard.read.requested")
        if not self._open():
            return None
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                logger.debug("clipboard.read.no_unicode_text")
                return None
            value = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            text = value if isinstance(value, str) else None
            logger.debug(
                "clipboard.read.completed text_length=%s text_preview=%s",
                len(text) if text is not None else None,
                text_preview(text),
            )
            return text
        except Exception:
            logger.exception("clipboard.read.failed")
            return None
        finally:
            self._close()

    @staticmethod
    def _close() -> None:
        try:
            win32clipboard.CloseClipboard()
            logger.debug("clipboard.closed")
        except Exception:
            logger.exception("clipboard.close.failed")
