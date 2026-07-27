import logging
import time

import win32clipboard
import win32con
from pynput.keyboard import Controller, Key

from .capture import fresh_clipboard_text
from .config import AppConfig
from .logging_setup import log_event, log_exception, text_preview

logger = logging.getLogger(__name__)


class ClipboardService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._keyboard = Controller()
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

    def write_text(self, text: str) -> bool:
        log_event(
            logger,
            logging.DEBUG,
            "clipboard.write.requested",
            text_length=len(text),
            text_preview=text_preview(text),
        )
        if not self._open():
            return False
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            log_event(logger, logging.DEBUG, "clipboard.write.completed")
            return True
        except Exception:
            log_exception(logger, "clipboard.write.failed")
            return False
        finally:
            self._close()

    def restore_text(
        self, text: str, retries: int = 5, initial_delay: float = 0.05
    ) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "clipboard.restore.started",
            text_length=len(text),
            retries=retries,
        )
        for attempt in range(retries):
            if self.write_text(text):
                log_event(
                    logger,
                    logging.DEBUG,
                    "clipboard.restore.completed",
                    attempt=attempt + 1,
                )
                return
            time.sleep(initial_delay * (2**attempt))
        log_event(
            logger,
            logging.WARNING,
            "clipboard.restore.failed",
            retries=retries,
        )

    def capture_selection(self) -> str:
        """Copy selected text and restore the previous text clipboard value."""
        original = self.read_text()
        baseline_sequence = win32clipboard.GetClipboardSequenceNumber()
        log_event(
            logger,
            logging.INFO,
            "selection_capture.started",
            baseline_sequence=baseline_sequence,
            original_length=len(original) if original is not None else None,
            original_preview=text_preview(original),
        )
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("c")
            self._keyboard.release("c")
        log_event(logger, logging.DEBUG, "selection_capture.ctrl_c_sent")

        deadline = time.monotonic() + self._config.clipboard_wait_seconds
        captured = None
        last_sequence = baseline_sequence
        while time.monotonic() < deadline:
            current_sequence = win32clipboard.GetClipboardSequenceNumber()
            if current_sequence != baseline_sequence:
                candidate = self.read_text()
                captured = fresh_clipboard_text(original, candidate)
                if current_sequence != last_sequence:
                    log_event(
                        logger,
                        logging.DEBUG,
                        "selection_capture.clipboard_changed",
                        sequence=current_sequence,
                        candidate_length=len(candidate)
                        if candidate is not None
                        else None,
                        candidate_preview=text_preview(candidate),
                        accepted=captured is not None,
                    )
                    last_sequence = current_sequence
                if captured is not None:
                    break
            time.sleep(self._config.clipboard_poll_seconds)

        if original is not None and captured is not None:
            self.restore_text(original)
        log_event(
            logger,
            logging.INFO if captured is not None else logging.WARNING,
            "selection_capture.completed",
            captured=captured is not None,
            captured_length=len(captured) if captured is not None else 0,
            captured_preview=text_preview(captured),
            final_sequence=win32clipboard.GetClipboardSequenceNumber(),
        )
        return captured or ""

    @staticmethod
    def _close() -> None:
        try:
            win32clipboard.CloseClipboard()
            log_event(logger, logging.DEBUG, "clipboard.closed")
        except Exception:
            log_exception(logger, "clipboard.close.failed")
