import json
import logging

from selectspeak.config import AppConfig
from selectspeak.logging_setup import JsonLineFormatter, configure_logging


def test_json_line_formatter_emits_structured_event() -> None:
    record = logging.LogRecord(
        name="selectspeak.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ignored message",
        args=(),
        exc_info=None,
    )
    record.event_name = "test.event"
    record.event_details = {"answer": 42}

    payload = json.loads(JsonLineFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["component"] == "selectspeak.test"
    assert payload["event"] == "test.event"
    assert payload["details"] == {"answer": 42}
    assert payload["timestamp"]
    assert payload["session"]


def test_logging_is_disabled_by_app_config() -> None:
    try:
        assert configure_logging(AppConfig(logging_enabled=False).logging) is None
        assert logging.root.manager.disable == logging.CRITICAL
    finally:
        logging.disable(logging.NOTSET)
