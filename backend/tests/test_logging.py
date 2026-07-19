import json
import logging

from src.logging_config import JsonFormatter, RequestContextFilter, request_id_context


def test_json_formatter_emits_structured_context():
    token = request_id_context.set("request-123")
    try:
        record = logging.LogRecord("backend.test", logging.INFO, __file__, 1, "done", (), None)
        record.event = "test.completed"
        RequestContextFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_context.reset(token)

    assert payload["message"] == "done"
    assert payload["request_id"] == "request-123"
    assert payload["event"] == "test.completed"


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.getLogger("backend.test").makeRecord(
            "backend.test", logging.ERROR, __file__, 1, "failed", (), __import__("sys").exc_info()
        )
    RequestContextFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]
