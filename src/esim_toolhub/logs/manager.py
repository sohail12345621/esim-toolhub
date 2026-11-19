"""Structured (JSON-lines) logging with secret redaction."""

from __future__ import annotations

import json
import logging
import logging.handlers
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from esim_toolhub.security.validation import redact

LOGGER_NAME = "esim_toolhub"
_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class RedactingFilter(logging.Filter):
    """Masks secrets in the message and in any structured ``extra`` fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = (
                tuple(redact(str(a)) for a in record.args)
                if isinstance(record.args, tuple)
                else record.args
            )
        for key, value in list(vars(record).items()):
            if key not in _STD_ATTRS and isinstance(value, str):
                setattr(record, key, redact(value))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="seconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = (
                    value if isinstance(value, (int, float, bool, type(None))) else str(value)
                )
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_file: Path, level: str = "INFO") -> logging.Logger:
    """Attach a rotating JSON file handler to the package logger (idempotent)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    for existing in list(logger.handlers):
        if existing.get_name() == "esim_toolhub_file":
            logger.removeHandler(existing)
            existing.close()
    handler: logging.Handler
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    handler.set_name("esim_toolhub_file")
    logger.addHandler(handler)
    return logger


@dataclass(frozen=True)
class LogEntry:
    ts: str
    level: str
    logger: str
    msg: str
    extra: dict[str, Any]


_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def read_logs(log_file: Path, tail: int = 50, min_level: str = "DEBUG") -> list[LogEntry]:
    """Return the last ``tail`` entries at or above ``min_level``. Malformed lines are skipped."""
    if not log_file.exists():
        return []
    threshold = _LEVELS.get(min_level.upper(), 10)
    entries: list[LogEntry] = []
    for line in log_file.read_text("utf-8", errors="replace").splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _LEVELS.get(str(data.get("level", "")).upper(), 0) < threshold:
            continue
        base = {k: data.pop(k, "") for k in ("ts", "level", "logger", "msg")}
        entries.append(LogEntry(extra=data, **{k: str(v) for k, v in base.items()}))
    return entries[-tail:] if tail > 0 else entries
