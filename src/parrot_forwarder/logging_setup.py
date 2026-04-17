"""
Structured JSON logging for ParrotForwarder v2.

Replaces v1's ``logging.basicConfig`` with a JSON formatter that every
downstream log tool (jq, Grafana Loki, Elastic) can ingest without
regex. Configuration is driven by ``LoggingConfig`` from the config
loader (:mod:`parrot_forwarder.config`).

The formatter is intentionally dependency-free: stdlib only, no
structlog. v2 keeps its dependency footprint minimal.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import LoggingConfig


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


#: Record attributes that are either stdlib boilerplate or formatted
#: separately; anything else passed via ``extra=`` becomes a top-level
#: JSON field.
_RESERVED_LOG_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record.

    Keys are stable and ordered: ``ts`` first, then ``level``, ``logger``,
    ``msg``, then every ``extra=`` field the caller passed. Exception
    info is rendered as a JSON-safe string under ``exception``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _format_ts(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Collect structured extras. Nested dicts are written through as-is.
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_ATTRS or key.startswith("_"):
                continue
            payload[key] = _jsonify(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, separators=(",", ":"), sort_keys=False, default=_fallback)


class TextFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)s %(message)s",
            datefmt="%H:%M:%S",
        )


def _format_ts(record: logging.LogRecord) -> str:
    # ``record.created`` is a POSIX timestamp; convert to UTC ISO-8601
    # with millisecond precision.
    dt = _dt.datetime.fromtimestamp(record.created, tz=_dt.UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _jsonify(value: Any) -> Any:
    """Best-effort conversion of non-JSON-native values."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    return repr(value)


def _fallback(value: Any) -> str:
    """json.dumps default= for anything _jsonify didn't catch."""
    return repr(value)


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


_OLYMPE_NOISY_LOGGERS = ("olympe", "ulog")


def configure_logging(config: LoggingConfig, *, also_stream: bool = True) -> None:
    """Install the JSON/Text formatters and the rotating file handler.

    Args:
        config: Logging section of the effective v2 config.
        also_stream: If ``True`` (default), also emit to stdout so
            systemd / journalctl keep seeing events. If ``False``, only
            the rotating file is used (useful for tests).
    """
    root = logging.getLogger()
    # Strip any previous handlers so re-configuring in tests is idempotent.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    level = getattr(logging, config.level.upper(), logging.INFO)
    root.setLevel(level)

    formatter = _build_formatter(config.format)

    # Rotating file handler. Create parent dir if needed - config.yaml
    # defaults to /var/log/parrot-forwarder which may not exist on a
    # dev host.
    log_path = Path(config.file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=config.rotation.max_bytes,
            backupCount=config.rotation.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)
    except OSError as exc:
        # e.g. permissions problem. Fall back to stream-only.
        print(f"WARNING: cannot open log file {log_path}: {exc}", file=sys.stderr)

    if also_stream:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)
        root.addHandler(stream_handler)

    # Tame Olympe's verbose output to WARNING unless the operator opted
    # into DEBUG globally.
    olympe_level = logging.DEBUG if level <= logging.DEBUG else logging.WARNING
    for name in _OLYMPE_NOISY_LOGGERS:
        logging.getLogger(name).setLevel(olympe_level)


def _build_formatter(name: str) -> logging.Formatter:
    if name == "json":
        return JsonFormatter()
    if name == "text":
        return TextFormatter()
    raise ValueError(f"unknown logging format: {name!r} (expected 'json' or 'text')")


# ---------------------------------------------------------------------------
# Convenience: context fields helper
# ---------------------------------------------------------------------------


def log_with_fields(logger: logging.Logger, level: str, message: str, **fields: Any) -> None:
    """Log ``message`` with structured ``fields`` under ``extra``.

    Equivalent to ``logger.info(message, extra={...})`` but centralizes
    the level lookup and ignores any protected keys that would clobber
    the stdlib LogRecord attributes.
    """
    lvl = getattr(logging, level.upper(), logging.INFO)
    safe_fields = {k: v for k, v in fields.items() if k not in _RESERVED_LOG_ATTRS}
    logger.log(lvl, message, extra=safe_fields)


def pid_fields() -> dict[str, int]:
    """Handy fields every long-lived process should add to its logs."""
    return {"pid": os.getpid()}
