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

from .config import AppConfig

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
            "event": getattr(record, "event_name", record.getMessage()),
        }
        details = getattr(record, "event_details", None)
        if details:
            payload["details"] = details
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(config: AppConfig) -> Path | None:
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

    log_event(
        logging.getLogger("selectspeak"),
        logging.INFO,
        "logging.configured",
        log_file=str(log_path.resolve()),
        process_id=os.getpid(),
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
        extra={
            "event_name": "process.unhandled_exception",
            "event_details": {},
        },
    )


def _thread_exception_hook(args: threading.ExceptHookArgs) -> None:
    exception = args.exc_value or RuntimeError(
        "Thread exited without an exception value"
    )
    logging.getLogger("selectspeak").critical(
        "thread.unhandled_exception",
        exc_info=(args.exc_type, exception, args.exc_traceback),
        extra={
            "event_name": "thread.unhandled_exception",
            "event_details": {"thread_name": args.thread.name if args.thread else None},
        },
    )


def _log_process_exit() -> None:
    log_event(logging.getLogger("selectspeak"), logging.INFO, "process.exiting")
    logging.shutdown()


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **details: Any,
) -> None:
    logger.log(
        level,
        event,
        extra={"event_name": event, "event_details": details},
    )


def log_exception(logger: logging.Logger, event: str, **details: Any) -> None:
    logger.error(
        event,
        exc_info=True,
        extra={"event_name": event, "event_details": details},
    )


def text_preview(text: str | None, limit: int = 120) -> str | None:
    if text is None:
        return None
    flattened = text.replace("\r", "\\r").replace("\n", "\\n")
    return flattened if len(flattened) <= limit else f"{flattened[:limit]}…"
