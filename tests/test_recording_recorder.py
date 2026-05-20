"""
Unit tests for the Recorder class.

These tests use a mock ``ffmpeg`` binary (a short shell script that reads
stdin, sleeps, and writes a configurable number of bytes to the output
path) so we can validate the recorder's lifecycle without real SRT.

Real-ffmpeg-against-SRT integration is covered by manual test T4 in the
sprint testing plan.
"""

from __future__ import annotations

import asyncio
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from parrot_forwarder.supervisor.recording.index import RecordingIndex
from parrot_forwarder.supervisor.recording.recorder import (
    AlreadyRecordingError,
    NotRecordingError,
    Recorder,
    RecordingMeta,
    RecordingStartFailed,
)


@pytest.fixture()
def mock_ffmpeg(tmp_path: Path) -> Path:
    """Write a fake ffmpeg that produces a file and sleeps until signalled.

    The script accepts (-i ... -map ... -c copy -f mpegts <outpath>) like real
    ffmpeg. It writes a fixed payload to the output path, then waits for a
    SIGINT/SIGTERM and exits 0.
    """
    script = tmp_path / "mock_ffmpeg.sh"
    script.write_text(
        """#!/bin/sh
# Last positional arg is the output file.
OUT=""
for arg in "$@"; do OUT="$arg"; done
# Emit a fake MPEG-TS payload so sha256 + size are meaningful.
printf 'FAKETS_VIDEO_KLV' > "$OUT"
# Install signal handlers that flush + exit 0 like real ffmpeg does on SIGINT.
trap 'printf "_TRAILER" >> "$OUT"; exit 0' INT TERM
# Stay alive.
while :; do sleep 0.05; done
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture()
def failing_ffmpeg(tmp_path: Path) -> Path:
    script = tmp_path / "fail_ffmpeg.sh"
    script.write_text(
        """#!/bin/sh
echo "srt: connection refused" >&2
exit 1
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture()
def ending_ffmpeg(tmp_path: Path) -> Path:
    """Write a fake ffmpeg that exits cleanly after the startup smoke window."""
    script = tmp_path / "ending_ffmpeg.sh"
    script.write_text(
        """#!/bin/sh
OUT=""
for arg in "$@"; do OUT="$arg"; done
printf 'PARTIAL_TS_CAPTURE' > "$OUT"
sleep 0.65
echo "size=16kB time=00:00:05.00 bitrate=26.2kbits/s speed=1x" >&2
exit 0
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture()
def async_failing_ffmpeg(tmp_path: Path) -> Path:
    """Write a fake ffmpeg that fails after start() has returned."""
    script = tmp_path / "async_fail_ffmpeg.sh"
    script.write_text(
        """#!/bin/sh
sleep 0.65
echo "srt: source disconnected" >&2
exit 2
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    p = tmp_path / "recordings"
    p.mkdir()
    return p


@pytest.fixture()
def index(root: Path) -> RecordingIndex:
    idx = RecordingIndex.open(root / "index.db")
    yield idx
    idx.close()


def _make_recorder(
    root: Path,
    index: RecordingIndex,
    ffmpeg: Path,
    events: list[tuple[str, dict]] | None = None,
) -> Recorder:
    async def sink(event_type: str, payload: dict[str, object]) -> None:
        if events is not None:
            events.append((event_type, payload))

    return Recorder(
        root_path=root,
        index=index,
        srt_port=8890,
        event_sink=sink if events is not None else None,
        ffmpeg_path=str(ffmpeg),
        fw_version="test",
    )


@pytest.mark.asyncio
async def test_start_creates_file_and_sidecar_and_row(
    root: Path, index: RecordingIndex, mock_ffmpeg: Path
) -> None:
    events: list[tuple[str, dict]] = []
    rec = _make_recorder(root, index, mock_ffmpeg, events)

    active = await rec.start(
        RecordingMeta(mission_id="m-test", drone_id="anafi01", session_id="sess1")
    )
    assert rec.is_running()
    assert active.mission_id == "m-test"
    assert active.drone_id == "anafi01"
    assert "m-test" in active.path
    # Give mock ffmpeg a moment to write its payload.
    await asyncio.sleep(0.1)
    ts_path = Path(active.path)
    assert ts_path.exists()
    sidecar_path = ts_path.with_suffix(".meta.json")
    assert sidecar_path.exists()
    sidecar = json.loads(sidecar_path.read_text())
    assert sidecar["recording_id"] == active.recording_id
    assert sidecar["mission_id"] == "m-test"
    assert sidecar["drone_id"] == "anafi01"
    assert sidecar["stopped_at"] is None

    row = index.get(active.recording_id)
    assert row is not None
    assert row.state == "active"

    assert events[0][0] == "recording.started"

    result = await rec.stop()
    assert result.bytes > 0
    assert result.sha256
    assert result.duration_s >= 0

    row_after = index.get(active.recording_id)
    assert row_after is not None
    assert row_after.state == "finalized"
    assert row_after.bytes == result.bytes
    assert row_after.sha256 == result.sha256

    sidecar_after = json.loads(sidecar_path.read_text())
    assert sidecar_after["stopped_at"] is not None
    assert sidecar_after["bytes"] == result.bytes
    assert sidecar_after["sha256"] == result.sha256

    assert any(evt[0] == "recording.stopped" for evt in events)
    assert not any(evt[0] == "recording.error" for evt in events)
    assert not rec.is_running()


@pytest.mark.asyncio
async def test_double_start_is_rejected(
    root: Path, index: RecordingIndex, mock_ffmpeg: Path
) -> None:
    rec = _make_recorder(root, index, mock_ffmpeg)
    await rec.start(RecordingMeta())
    try:
        with pytest.raises(AlreadyRecordingError):
            await rec.start(RecordingMeta())
    finally:
        await rec.stop()


@pytest.mark.asyncio
async def test_stop_without_start_raises(
    root: Path, index: RecordingIndex, mock_ffmpeg: Path
) -> None:
    rec = _make_recorder(root, index, mock_ffmpeg)
    with pytest.raises(NotRecordingError):
        await rec.stop()


@pytest.mark.asyncio
async def test_ffmpeg_failure_is_surfaced(
    root: Path, index: RecordingIndex, failing_ffmpeg: Path
) -> None:
    rec = _make_recorder(root, index, failing_ffmpeg)
    caught_sync = False
    try:
        await rec.start(RecordingMeta())
    except RecordingStartFailed:
        caught_sync = True
    if not caught_sync:
        # Fall-through path: watchdog will mark it async.
        await asyncio.sleep(0.5)
    rows = index.list()
    assert len(rows) == 1
    assert rows[0].state == "error"
    assert rows[0].error_reason  # something about connection refused


@pytest.mark.asyncio
async def test_autonomous_clean_ffmpeg_exit_finalizes_existing_file(
    root: Path, index: RecordingIndex, ending_ffmpeg: Path
) -> None:
    events: list[tuple[str, dict]] = []
    rec = _make_recorder(root, index, ending_ffmpeg, events)

    active = await rec.start(RecordingMeta(notes="field ended"))
    deadline = asyncio.get_running_loop().time() + 2
    row = index.get(active.recording_id)
    while row is not None and row.state == "active" and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)
        row = index.get(active.recording_id)

    assert row is not None
    assert row.state == "finalized"
    assert row.bytes == len(b"PARTIAL_TS_CAPTURE")
    assert row.sha256
    assert not rec.is_running()

    stopped_events = [evt for evt in events if evt[0] == "recording.stopped"]
    assert stopped_events
    assert stopped_events[-1][1]["interrupted"] is True
    assert stopped_events[-1][1]["finalized_reason"] == "source_ended"
    assert not any(evt[0] == "recording.error" for evt in events)

    sidecar = json.loads(Path(active.path).with_suffix(".meta.json").read_text())
    assert sidecar["interrupted"] is True
    assert sidecar["finalized_reason"] == "source_ended"


@pytest.mark.asyncio
async def test_autonomous_nonzero_ffmpeg_exit_remains_error(
    root: Path, index: RecordingIndex, async_failing_ffmpeg: Path
) -> None:
    events: list[tuple[str, dict]] = []
    rec = _make_recorder(root, index, async_failing_ffmpeg, events)

    active = await rec.start(RecordingMeta())
    deadline = asyncio.get_running_loop().time() + 2
    row = index.get(active.recording_id)
    while row is not None and row.state == "active" and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)
        row = index.get(active.recording_id)

    assert row is not None
    assert row.state == "error"
    assert row.error_reason == "srt: source disconnected"
    assert not rec.is_running()
    assert any(evt[0] == "recording.error" for evt in events)
    assert not any(evt[0] == "recording.stopped" for evt in events)


@pytest.mark.asyncio
async def test_manual_stop_is_not_reported_as_watchdog_error(
    root: Path, index: RecordingIndex, mock_ffmpeg: Path
) -> None:
    events: list[tuple[str, dict]] = []
    rec = _make_recorder(root, index, mock_ffmpeg, events)

    active = await rec.start(RecordingMeta())
    await asyncio.sleep(0.1)
    result = await rec.stop()
    await asyncio.sleep(0.1)

    row = index.get(active.recording_id)
    assert row is not None
    assert row.state == "finalized"
    assert result.bytes > 0
    assert any(evt[0] == "recording.stopped" for evt in events)
    assert not any(evt[0] == "recording.error" for evt in events)


@pytest.mark.asyncio
async def test_missing_ffmpeg_binary_raises(
    root: Path, index: RecordingIndex, tmp_path: Path
) -> None:
    rec = Recorder(
        root_path=root,
        index=index,
        srt_port=8890,
        ffmpeg_path=str(tmp_path / "does_not_exist"),
    )
    with pytest.raises(RecordingStartFailed):
        await rec.start(RecordingMeta())


def test_reconcile_finalizes_orphan_with_file(
    root: Path, index: RecordingIndex, tmp_path: Path
) -> None:
    # Simulate a crashed prior run: active row + existing file on disk.
    active_file = root / "2026-04-19" / "default" / "drone_sess_2026-04-19T12-00-00Z.ts"
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_bytes(b"PARTIAL_CAPTURE")
    index.insert_active(
        recording_id="orphan1",
        path=str(active_file),
        started_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
    )
    rec = Recorder(root_path=root, index=index, srt_port=8890, ffmpeg_path="/bin/true")
    reconciled = rec.reconcile_active_rows()
    assert len(reconciled) == 1
    row = index.get("orphan1")
    assert row is not None
    assert row.state == "finalized"
    assert row.bytes == len(b"PARTIAL_CAPTURE")
    assert row.sha256


def test_reconcile_marks_orphan_error_if_file_missing(
    root: Path, index: RecordingIndex
) -> None:
    index.insert_active(
        recording_id="orphan2",
        path=str(root / "no" / "such" / "file.ts"),
        started_at=datetime(2026, 4, 19, tzinfo=UTC),
    )
    rec = Recorder(root_path=root, index=index, srt_port=8890, ffmpeg_path="/bin/true")
    rec.reconcile_active_rows()
    row = index.get("orphan2")
    assert row is not None
    assert row.state == "error"
    assert "crash" in (row.error_reason or "")


def test_file_path_layout(
    root: Path, index: RecordingIndex, mock_ffmpeg: Path
) -> None:
    # Direct test of the path builder via a start/stop cycle.
    # We inspect the created file's relative path shape.
    async def _go() -> Path:
        rec = _make_recorder(root, index, mock_ffmpeg)
        active = await rec.start(
            RecordingMeta(
                mission_id="alpha",
                drone_id="anafi42",
                session_id="controller-a",
                notes="field test",
            )
        )
        await asyncio.sleep(0.05)
        await rec.stop()
        return Path(active.path)

    path = asyncio.run(_go())
    parts = path.relative_to(root).parts
    # <date>/<mission>/<notes>_<iso>.ts
    assert parts[0].startswith("20")  # YYYY-...
    assert parts[1] == "alpha"
    assert parts[2].startswith("field_test_")
    assert "anafi42" not in parts[2]
    assert "controller-a" not in parts[2]
    assert parts[2].endswith(".ts")


def test_status_reports_active_fields(
    root: Path, index: RecordingIndex, mock_ffmpeg: Path
) -> None:
    async def _go() -> None:
        rec = _make_recorder(root, index, mock_ffmpeg)
        assert rec.status() == {"active": False}
        active = await rec.start(
            RecordingMeta(mission_id="m", drone_id="d", session_id="s")
        )
        await asyncio.sleep(0.1)
        status = rec.status()
        assert status["active"] is True
        assert status["recording_id"] == active.recording_id
        assert status["mission_id"] == "m"
        assert status["drone_id"] == "d"
        assert isinstance(status["elapsed_s"], float)
        await rec.stop()
        assert rec.status() == {"active": False}

    asyncio.run(_go())
