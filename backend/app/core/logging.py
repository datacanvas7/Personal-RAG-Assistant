"""Logging configuration shared by the API and the worker.

Two output formats: readable text for a developer's terminal and one JSON object per line
for log collectors (``LOG_FORMAT=json``). Every record carries the id of the request that
caused it (``request_id``), so one request can be followed through the whole log.

What is never logged: passwords, tokens, document text, questions and answers. Request
logs contain the method, the path (no query string), the status and the duration.
"""

import json
import logging
import logging.config
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

# Set by the request middleware for the duration of one request; "-" outside a request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes every LogRecord has. Anything else was passed with ``extra=`` and is exported
# as a field in JSON output.
_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()) | {
    "message",
    "asctime",
    "request_id",
    "taskName",
}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _RECORD_FIELDS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str, log_format: Literal["text", "json"] = "text") -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "text": {
                    "format": "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
                },
                "json": {"()": JsonFormatter},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": log_format,
                    "filters": ["request_id"],
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {"level": level, "handlers": ["console"]},
        }
    )
