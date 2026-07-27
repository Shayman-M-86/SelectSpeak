import logging
import time

import win32clipboard
import win32con

from .logging_setup import log_event, log_exception, text_preview

logger = logging.getLogger(__name__)


class ClipboardService:
    def __init__(self) -> None:
        log_event(logger, logging.DEBUG, "clipboard.service.created")

    @staticmethod
    def _open(retries: int = 5, delay: float = 0.05) -> bool:
        for attempt in range(1, retries + 1):
            try:
                win32clipboard.OpenClipboard()
                log_event(
                    logger,
                    logging.DEBUG,
                    "clipboard.opened",
                    attempt=attempt,
                )
                return True
            except Exception:
                log_event(
                    logger,
                    logging.DEBUG,
                    "clipboard.open.retry",
                    attempt=attempt,
                    retries=retries,
                )
                time.sleep(delay)
        log_event(
            logger,
            logging.WARNING,
            "clipboard.open.failed",
            retries=retries,
        )
        return False

    def read_text(self) -> str | None:
        log_event(logger, logging.DEBUG, "clipboard.read.requested")
        if not self._open():
            return None
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                log_event(logger, logging.DEBUG, "clipboard.read.no_unicode_text")
                return None
            value = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            text = value if isinstance(value, str) else None
            log_event(
                logger,
                logging.DEBUG,
                "clipboard.read.completed",
                text_length=len(text) if text is not None else None,
                text_preview=text_preview(text),
            )
            return text
        except Exception:
            log_exception(logger, "clipboard.read.failed")
            return None
        finally:
            self._close()

    @staticmethod
    def _close() -> None:
        try:
            win32clipboard.CloseClipboard()
            log_event(logger, logging.DEBUG, "clipboard.closed")
        except Exception:
            log_exception(logger, "clipboard.close.failed")
