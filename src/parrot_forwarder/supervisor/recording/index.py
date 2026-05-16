"""
SQLite-backed index of drone recordings.

The index lives at ``<recordings_path>/index.db`` and is the authoritative
list of ``.ts`` captures produced by the supervisor. File listing endpoints
read from the index rather than walking the filesystem: directory walks on
large archives over VirtioFS (macOS Docker Desktop) are slow enough to
matter at O(1000) files.

All writes use WAL mode so concurrent readers on the dashboard never see a
torn row. The database is created at :meth:`RecordingIndex.open` if missing
and migrations are idempotent.

Deletion is permanent: the API removes the capture file, sidecar, and index
row. The ``deleted`` state remains in the schema only so older field databases
can still be opened and purged after upgrading from the previous soft-delete
behavior.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

RecordingState = Literal["active", "finalized", "error", "deleted"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    drone_id TEXT,
    session_id TEXT,
    mission_id TEXT,
    path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    stopped_at TEXT,
    duration_s INTEGER,
    bytes INTEGER,
    sha256 TEXT,
    state TEXT NOT NULL CHECK(state IN ('active','finalized','error','deleted')),
    notes TEXT,
    trigger TEXT,
    error_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_recordings_started_at
    ON recordings (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_recordings_state
    ON recordings (state);

CREATE INDEX IF NOT EXISTS idx_recordings_mission
    ON recordings (mission_id);
"""


@dataclass(frozen=True)
class RecordingRow:
    """A single row of the recordings index, as surfaced to callers."""

    id: str
    path: str
    started_at: str
    stopped_at: str | None
    duration_s: int | None
    bytes: int | None
    sha256: str | None
    state: RecordingState
    drone_id: str | None
    session_id: str | None
    mission_id: str | None
    notes: str | None
    trigger: str | None
    error_reason: str | None


@dataclass(frozen=True)
class DiskUsage:
    used_bytes: int
    free_bytes: int
    total_bytes: int
    count: int


class RecordingIndex:
    """Thread-safe handle to the recordings SQLite index."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @classmethod
    def open(cls, db_path: Path) -> RecordingIndex:
        idx = cls(db_path)
        idx._connect()
        return idx

    @property
    def path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def insert_active(
        self,
        *,
        recording_id: str,
        path: str,
        started_at: datetime,
        drone_id: str | None = None,
        session_id: str | None = None,
        mission_id: str | None = None,
        notes: str | None = None,
        trigger: str | None = None,
    ) -> None:
        self._exec(
            """
            INSERT INTO recordings (
                id, path, started_at, drone_id, session_id, mission_id,
                notes, trigger, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                recording_id,
                path,
                _iso(started_at),
                drone_id,
                session_id,
                mission_id,
                notes,
                trigger,
            ),
        )

    def finalize(
        self,
        recording_id: str,
        *,
        bytes_: int,
        sha256: str,
        stopped_at: datetime,
    ) -> None:
        started_at = self._started_at(recording_id)
        duration_s = None
        if started_at is not None:
            duration_s = int((stopped_at - started_at).total_seconds())
        self._exec(
            """
            UPDATE recordings
            SET state='finalized',
                stopped_at=?,
                duration_s=?,
                bytes=?,
                sha256=?
            WHERE id=?
            """,
            (_iso(stopped_at), duration_s, bytes_, sha256, recording_id),
        )

    def mark_error(self, recording_id: str, reason: str) -> None:
        self._exec(
            "UPDATE recordings SET state='error', error_reason=? WHERE id=?",
            (reason, recording_id),
        )

    def delete(self, recording_id: str) -> None:
        self._exec("DELETE FROM recordings WHERE id=?", (recording_id,))

    def get(self, recording_id: str) -> RecordingRow | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM recordings WHERE id=?",
                (recording_id,),
            )
            row = cur.fetchone()
            return _row(row) if row else None

    def list(
        self,
        *,
        state: RecordingState | None = None,
        mission_id: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[RecordingRow]:
        clauses: list[str] = []
        params: list[object] = []
        if state is not None:
            clauses.append("state=?")
            params.append(state)
        if mission_id is not None:
            clauses.append("mission_id=?")
            params.append(mission_id)
        if since is not None:
            clauses.append("started_at>=?")
            params.append(_iso(since))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM recordings {where} "
                "ORDER BY started_at DESC LIMIT ?",
                params,
            )
            return [_row(r) for r in cur.fetchall()]

    def iter_active(self) -> Iterator[RecordingRow]:
        """Rows still in ``active`` state - used for crash recovery."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM recordings WHERE state='active'")
            for r in cur.fetchall():
                yield _row(r)

    def count(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM recordings")
            return int(cur.fetchone()[0])

    # ------------------------------------------------------------------
    # Disk usage
    # ------------------------------------------------------------------

    def disk_usage(self, root: Path) -> DiskUsage:
        """Return host-visible usage for the recordings root.

        Uses ``os.statvfs`` so the numbers match what the host filesystem
        reports to the operator (via Finder).
        """
        import os

        stats = os.statvfs(root)
        total = stats.f_frsize * stats.f_blocks
        free = stats.f_frsize * stats.f_bavail
        used = total - free
        return DiskUsage(
            used_bytes=used,
            free_bytes=free,
            total_bytes=total,
            count=self.count(),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._db_path),
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        self._conn = conn

    def _exec(self, sql: str, params: tuple[object, ...]) -> None:
        with self._lock:
            assert self._conn is not None, "index not opened"
            self._conn.execute(sql, params)

    def _started_at(self, recording_id: str) -> datetime | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT started_at FROM recordings WHERE id=?",
                (recording_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return _parse_iso(row["started_at"])

    def _cursor(self) -> _CursorCtx:
        return _CursorCtx(self)


class _CursorCtx:
    def __init__(self, idx: RecordingIndex) -> None:
        self._idx = idx
        self._cur: sqlite3.Cursor | None = None

    def __enter__(self) -> sqlite3.Cursor:
        self._idx._lock.acquire()
        conn = self._idx._conn
        assert conn is not None, "index not opened"
        self._cur = conn.cursor()
        return self._cur

    def __exit__(self, *_exc: object) -> None:
        if self._cur is not None:
            self._cur.close()
        self._idx._lock.release()


def _row(r: sqlite3.Row) -> RecordingRow:
    return RecordingRow(
        id=r["id"],
        path=r["path"],
        started_at=r["started_at"],
        stopped_at=r["stopped_at"],
        duration_s=r["duration_s"],
        bytes=r["bytes"],
        sha256=r["sha256"],
        state=r["state"],
        drone_id=r["drone_id"],
        session_id=r["session_id"],
        mission_id=r["mission_id"],
        notes=r["notes"],
        trigger=r["trigger"],
        error_reason=r["error_reason"],
    )


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
