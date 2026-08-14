import json
import logging

from selectspeak.config import AppConfig
from selectspeak.infrastructure.logging import JsonLineFormatter, configure_logging


def test_logging_is_disabled_by_default() -> None:
    assert not AppConfig().logging_enabled


def test_json_line_formatter_emits_record_metadata() -> None:
    record = logging.LogRecord(
        name="selectspeak.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="test.event",
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonLineFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["component"] == "selectspeak.test"
    assert payload["event"] == "test.event"
    assert "details" not in payload
    assert payload["timestamp"]
    assert payload["session"]


def test_json_line_formatter_accepts_standard_logger_messages() -> None:
    record = logging.LogRecord(
        name="selectspeak.app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="app.started hotkey=%s",
        args=("alt+s",),
        exc_info=None,
    )

    payload = json.loads(JsonLineFormatter().format(record))

    assert payload["component"] == "selectspeak.app"
    assert payload["event"] == "app.started hotkey=alt+s"
    assert "details" not in payload


def test_logging_is_disabled_by_app_config() -> None:
    try:
        assert configure_logging(AppConfig(logging_enabled=False).logging) is None
        assert logging.root.manager.disable == logging.CRITICAL
    finally:
        logging.disable(logging.NOTSET)
