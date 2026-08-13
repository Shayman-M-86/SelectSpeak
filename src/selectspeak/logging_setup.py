import atexit
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import LoggingConfig

_SESSION_ID = uuid4().hex


class JsonLineFormatter(logging.Formatter):
    """Format each record as one compact, chronologically sortable JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "component": record.name,
            "thread": record.threadName or threading.current_thread().name,
            "session": _SESSION_ID,
            "event": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(config: LoggingConfig) -> Path | None:
    """Configure diagnostics from the application configuration."""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    if not config.logging_enabled:
        logging.captureWarnings(False)
        logging.disable(logging.CRITICAL)
        return None

    logging.disable(logging.NOTSET)
    log_path = Path(config.log_file).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger.setLevel(logging.DEBUG)

    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JsonLineFormatter())
    root_logger.addHandler(handler)
    logging.captureWarnings(True)
    sys.excepthook = _process_exception_hook
    threading.excepthook = _thread_exception_hook
    atexit.register(_log_process_exit)

    logging.getLogger("selectspeak").info(
        "logging.configured log_file=%s process_id=%s",
        str(log_path.resolve()),
        os.getpid(),
    )
    return log_path


def _process_exception_hook(
    exception_type: type[BaseException],
    exception: BaseException,
    traceback: Any,
) -> None:
    logging.getLogger("selectspeak").critical(
        "process.unhandled_exception",
        exc_info=(exception_type, exception, traceback),
    )


def _thread_exception_hook(args: threading.ExceptHookArgs) -> None:
    exception = args.exc_value or RuntimeError("Thread exited without an exception value")
    logging.getLogger("selectspeak").critical(
        "thread.unhandled_exception thread_name=%s",
        args.thread.name if args.thread else None,
        exc_info=(args.exc_type, exception, args.exc_traceback),
    )


def _log_process_exit() -> None:
    logging.getLogger("selectspeak").info("process.exiting")
    logging.shutdown()


def text_preview(text: str | None, limit: int = 120) -> str | None:
    if text is None:
        return None
    flattened = text.replace("\r", "\\r").replace("\n", "\\n")
    return flattened if len(flattened) <= limit else f"{flattened[:limit]}…"
