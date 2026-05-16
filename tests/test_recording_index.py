"""
Unit tests for the SQLite-backed recordings index.

Covered behaviours:

- Schema is created idempotently (open twice is fine).
- Insert active -> list returns it with state='active'.
- Finalize updates state + stopped_at + bytes + sha256 + duration.
- Mark error updates state + error_reason.
- Delete removes rows permanently.
- Crash-reopen: active rows are enumerable via ``iter_active`` so the
  supervisor can reconcile them on startup.
- List filters (state, mission_id, since) + limit.
- Disk usage reports non-zero totals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from parrot_forwarder.supervisor.recording.index import (
    RecordingIndex,
    RecordingRow,
)


def _mkdt(offset_s: int = 0) -> datetime:
    return datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_s)


@pytest.fixture()
def index(tmp_path: Path) -> RecordingIndex:
    db = tmp_path / "index.db"
    idx = RecordingIndex.open(db)
    yield idx
    idx.close()


def test_open_creates_schema_idempotently(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    idx1 = RecordingIndex.open(db)
    idx1.close()
    idx2 = RecordingIndex.open(db)
    assert idx2.count() == 0
    idx2.close()


def test_insert_and_get(index: RecordingIndex) -> None:
    index.insert_active(
        recording_id="r1",
        path="/recordings/x.ts",
        started_at=_mkdt(),
        drone_id="anafi01",
        session_id="s1",
        mission_id="m1",
        notes="first",
        trigger="manual",
    )
    row = index.get("r1")
    assert isinstance(row, RecordingRow)
    assert row.id == "r1"
    assert row.state == "active"
    assert row.drone_id == "anafi01"
    assert row.session_id == "s1"
    assert row.mission_id == "m1"
    assert row.notes == "first"
    assert row.trigger == "manual"
    assert row.stopped_at is None


def test_finalize_sets_duration_and_bytes(index: RecordingIndex) -> None:
    index.insert_active(
        recording_id="r1",
        path="/r/x.ts",
        started_at=_mkdt(),
    )
    index.finalize(
        "r1",
        bytes_=123_456,
        sha256="deadbeef",
        stopped_at=_mkdt(30),
    )
    row = index.get("r1")
    assert row is not None
    assert row.state == "finalized"
    assert row.bytes == 123_456
    assert row.sha256 == "deadbeef"
    assert row.duration_s == 30
    assert row.stopped_at is not None


def test_mark_error_updates_reason(index: RecordingIndex) -> None:
    index.insert_active(recording_id="r1", path="/r/x.ts", started_at=_mkdt())
    index.mark_error("r1", "ffmpeg exited non-zero")
    row = index.get("r1")
    assert row is not None
    assert row.state == "error"
    assert row.error_reason == "ffmpeg exited non-zero"


def test_delete_removes_row(index: RecordingIndex) -> None:
    index.insert_active(recording_id="r1", path="/r/x.ts", started_at=_mkdt())
    index.finalize("r1", bytes_=1, sha256="x", stopped_at=_mkdt(1))
    index.delete("r1")
    assert index.get("r1") is None


def test_list_filters_by_state_mission_and_since(index: RecordingIndex) -> None:
    index.insert_active(recording_id="a", path="/r/a.ts", started_at=_mkdt(0), mission_id="m1")
    index.insert_active(recording_id="b", path="/r/b.ts", started_at=_mkdt(60), mission_id="m2")
    index.insert_active(recording_id="c", path="/r/c.ts", started_at=_mkdt(120), mission_id="m1")
    index.finalize("a", bytes_=1, sha256="x", stopped_at=_mkdt(30))

    all_rows = index.list()
    assert [r.id for r in all_rows] == ["c", "b", "a"]

    active_only = index.list(state="active")
    assert {r.id for r in active_only} == {"b", "c"}

    mission_m1 = index.list(mission_id="m1")
    assert {r.id for r in mission_m1} == {"a", "c"}

    since = index.list(since=_mkdt(60))
    assert {r.id for r in since} == {"b", "c"}


def test_list_respects_limit(index: RecordingIndex) -> None:
    for i in range(10):
        index.insert_active(
            recording_id=f"r{i}",
            path=f"/r/{i}.ts",
            started_at=_mkdt(i),
        )
    assert len(index.list(limit=3)) == 3


def test_iter_active_enumerates_unfinalized(index: RecordingIndex) -> None:
    index.insert_active(recording_id="a", path="/r/a.ts", started_at=_mkdt())
    index.insert_active(recording_id="b", path="/r/b.ts", started_at=_mkdt(1))
    index.finalize("a", bytes_=1, sha256="x", stopped_at=_mkdt(2))
    ids = {r.id for r in index.iter_active()}
    assert ids == {"b"}


def test_crash_reopen_preserves_active(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    idx = RecordingIndex.open(db)
    idx.insert_active(recording_id="r1", path="/r/x.ts", started_at=_mkdt())
    idx.close()

    reopened = RecordingIndex.open(db)
    try:
        ids = {r.id for r in reopened.iter_active()}
        assert ids == {"r1"}
    finally:
        reopened.close()


def test_disk_usage_uses_statvfs(index: RecordingIndex, tmp_path: Path) -> None:
    usage = index.disk_usage(tmp_path)
    assert usage.total_bytes > 0
    assert usage.free_bytes >= 0
    assert usage.used_bytes == usage.total_bytes - usage.free_bytes
    assert usage.count == 0
    index.insert_active(recording_id="r1", path="/r/x.ts", started_at=_mkdt())
    assert index.disk_usage(tmp_path).count == 1
