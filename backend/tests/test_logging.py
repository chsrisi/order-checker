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


def test_configure_logging_defaults(monkeypatch, tmp_path):
    from src import logging_config

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_TO_FILE", "true")
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_LEVEL_CONSOLE", raising=False)
    monkeypatch.delenv("LOG_LEVEL_FILE", raising=False)

    logging_config.configure_logging()
    root = logging.getLogger()

    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler)]
    file_handlers = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]

    assert len(stream_handlers) == 1
    assert stream_handlers[0].level == logging.WARNING

    assert len(file_handlers) == 1
    assert file_handlers[0].level == logging.DEBUG

    assert root.level == logging.DEBUG


def test_configure_logging_console_only(monkeypatch):
    from src import logging_config

    monkeypatch.setenv("LOG_TO_FILE", "false")
    monkeypatch.setenv("LOG_LEVEL_CONSOLE", "INFO")

    logging_config.configure_logging()
    root = logging.getLogger()

    file_handlers = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(file_handlers) == 0
    assert root.level == logging.INFO


def test_configure_logging_overrides(monkeypatch, tmp_path):
    from src import logging_config

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_TO_FILE", "true")
    monkeypatch.setenv("LOG_LEVEL_CONSOLE", "ERROR")
    monkeypatch.setenv("LOG_LEVEL_FILE", "INFO")

    logging_config.configure_logging()
    root = logging.getLogger()

    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler)]
    file_handlers = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]

    assert stream_handlers[0].level == logging.ERROR
    assert file_handlers[0].level == logging.INFO
    assert root.level == logging.INFO

