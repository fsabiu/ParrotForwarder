"""
Tests for the structured JSON logging setup.

Each test reconfigures the root logger; the setup is idempotent but
we also clear handlers in teardown to keep tests hermetic.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from parrot_forwarder.config import load_config
from parrot_forwarder.logging_setup import (
    JsonFormatter,
    configure_logging,
    log_with_fields,
)


@pytest.fixture(autouse=True)
def _reset_root_logger() -> None:
    """Make sure each test starts from a clean root logger."""
    root = logging.getLogger()
    saved = list(root.handlers), root.level
    for h in list(root.handlers):
        root.removeHandler(h)
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved[0]:
        root.addHandler(h)
    root.setLevel(saved[1])


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------


def test_json_formatter_emits_expected_keys() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    out = JsonFormatter().format(record)
    parsed = json.loads(out)
    assert set(parsed) >= {"ts", "level", "logger", "msg"}
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test"
    assert parsed["msg"] == "hello world"
    # ts is ISO-8601 UTC with millisecond precision + Z suffix.
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", parsed["ts"]), parsed["ts"]


def test_json_formatter_includes_extra_fields() -> None:
    logger = logging.getLogger("test_with_extra")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    import io

    buf = io.StringIO()
    handler.stream = buf

    logger.info("state transition", extra={"event": "state_transition", "to": "STREAMING"})
    parsed = json.loads(buf.getvalue().strip())
    assert parsed["event"] == "state_transition"
    assert parsed["to"] == "STREAMING"


def test_json_formatter_renders_exception_as_string() -> None:
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            name="t", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="bad", args=(), exc_info=sys.exc_info(),
        )
        out = JsonFormatter().format(record)
        parsed = json.loads(out)
        assert "exception" in parsed
        assert "kaboom" in parsed["exception"]


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


def test_configure_logging_writes_rotating_file(tmp_path: Path) -> None:
    cfg = load_config(
        cli_overrides={
            "logging": {
                "level": "DEBUG",
                "format": "json",
                "file": str(tmp_path / "pf.log"),
                "rotation": {"max_bytes": 10_000, "backup_count": 2},
            }
        }
    )
    configure_logging(cfg.logging, also_stream=False)
    logging.getLogger("pf.test").info("hello")
    for h in logging.getLogger().handlers:
        h.flush()

    content = (tmp_path / "pf.log").read_text()
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert lines, "file handler must have written at least one line"
    last = json.loads(lines[-1])
    assert last["msg"] == "hello"
    assert last["logger"] == "pf.test"


def test_configure_logging_respects_level(tmp_path: Path) -> None:
    cfg = load_config(
        cli_overrides={
            "logging": {
                "level": "WARNING",
                "format": "json",
                "file": str(tmp_path / "pf.log"),
            }
        }
    )
    configure_logging(cfg.logging, also_stream=False)
    logger = logging.getLogger("pf.level")
    logger.info("should not appear")
    logger.warning("should appear")
    for h in logging.getLogger().handlers:
        h.flush()

    lines = [ln for ln in (tmp_path / "pf.log").read_text().splitlines() if ln.strip()]
    messages = [json.loads(ln)["msg"] for ln in lines]
    assert "should appear" in messages
    assert "should not appear" not in messages


def test_configure_logging_rejects_unknown_format(tmp_path: Path) -> None:
    cfg = load_config(
        cli_overrides={
            "logging": {
                "level": "INFO",
                # Bypass pydantic enum via mutation - we can't actually create
                # an invalid config through load_config. Test the inner
                # formatter factory directly.
                "file": str(tmp_path / "pf.log"),
            }
        }
    )
    cfg_copy = cfg.logging.model_copy(update={"format": "xml"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown logging format"):
        configure_logging(cfg_copy, also_stream=False)


def test_configure_logging_tames_olympe_loggers(tmp_path: Path) -> None:
    cfg = load_config(
        cli_overrides={
            "logging": {
                "level": "INFO",
                "format": "json",
                "file": str(tmp_path / "pf.log"),
            }
        }
    )
    configure_logging(cfg.logging, also_stream=False)
    assert logging.getLogger("olympe").level == logging.WARNING
    assert logging.getLogger("ulog").level == logging.WARNING


def test_configure_logging_debug_level_unlocks_olympe(tmp_path: Path) -> None:
    cfg = load_config(
        cli_overrides={
            "logging": {
                "level": "DEBUG",
                "format": "json",
                "file": str(tmp_path / "pf.log"),
            }
        }
    )
    configure_logging(cfg.logging, also_stream=False)
    assert logging.getLogger("olympe").level == logging.DEBUG


# ---------------------------------------------------------------------------
# log_with_fields helper
# ---------------------------------------------------------------------------


def test_log_with_fields_passes_structured_extras(tmp_path: Path) -> None:
    cfg = load_config(
        cli_overrides={
            "logging": {
                "level": "INFO",
                "format": "json",
                "file": str(tmp_path / "pf.log"),
            }
        }
    )
    configure_logging(cfg.logging, also_stream=False)
    log_with_fields(
        logging.getLogger("pf.helper"),
        "info",
        "state transition",
        event="state_transition",
        **{"from": "READY"},
        to="STREAMING",
    )
    for h in logging.getLogger().handlers:
        h.flush()
    last = json.loads(
        [ln for ln in (tmp_path / "pf.log").read_text().splitlines() if ln.strip()][-1]
    )
    assert last["event"] == "state_transition"
    assert last["from"] == "READY"
    assert last["to"] == "STREAMING"


def test_log_with_fields_drops_reserved_keys(tmp_path: Path) -> None:
    cfg = load_config(
        cli_overrides={
            "logging": {
                "level": "INFO",
                "format": "json",
                "file": str(tmp_path / "pf.log"),
            }
        }
    )
    configure_logging(cfg.logging, also_stream=False)
    # "msg" and "levelname" are stdlib LogRecord attrs; passing them via
    # extra= would raise KeyError. log_with_fields must filter them.
    log_with_fields(
        logging.getLogger("pf.helper"),
        "info",
        "hi",
        msg="this should be dropped",
        levelname="FAKE",
        custom="keeps me",
    )
    for h in logging.getLogger().handlers:
        h.flush()
    last = json.loads(
        [ln for ln in (tmp_path / "pf.log").read_text().splitlines() if ln.strip()][-1]
    )
    assert last["msg"] == "hi", "reserved msg must not be overridden by extra"
    assert last["custom"] == "keeps me"
