"""
Integration tests for the recording API router.

Uses FastAPI's ``TestClient`` with a real Recorder pointed at a fake ffmpeg
script (same pattern as ``test_recording_recorder.py``). The supervisor
is a thin fake because the recording router does not depend on it.
"""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from parrot_forwarder import ipc as ipc_module
from parrot_forwarder.supervisor import Supervisor, WorkerHandle
from parrot_forwarder.supervisor.api import create_app
from parrot_forwarder.supervisor.recording.index import RecordingIndex
from parrot_forwarder.supervisor.recording.recorder import Recorder


@pytest.fixture()
def mock_ffmpeg(tmp_path: Path) -> Path:
    script = tmp_path / "mock_ffmpeg.sh"
    script.write_text(
        """#!/bin/sh
OUT=""
for arg in "$@"; do OUT="$arg"; done
printf 'TS_VIDEO+KLV' > "$OUT"
trap 'printf "_END" >> "$OUT"; exit 0' INT TERM
while :; do sleep 0.05; done
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _stub_worker_factory() -> Any:
    async def _factory(_sup: Supervisor) -> WorkerHandle:
        exited: asyncio.Future[int] = asyncio.get_event_loop().create_future()

        async def send(_m: ipc_module._IpcBase) -> None:
            pass

        async def close() -> None:
            if not exited.done():
                exited.set_result(0)

        return WorkerHandle(pid=1, send=send, close=close, exited=exited)

    return _factory


@pytest.fixture()
def app_and_root(tmp_path: Path, mock_ffmpeg: Path):
    root = tmp_path / "recs"
    root.mkdir()
    index = RecordingIndex.open(root / "index.db")
    recorder = Recorder(
        root_path=root,
        index=index,
        srt_port=8890,
        ffmpeg_path=str(mock_ffmpeg),
    )
    sup = Supervisor(
        worker_factory=_stub_worker_factory(),
        auto_start=False,
        start_enabled=False,
    )
    app = create_app(
        sup,
        config=None,
        recorder=recorder,
        recording_index=index,
        recordings_root=root,
    )
    yield app, root, recorder, index
    try:
        asyncio.new_event_loop().run_until_complete(recorder.shutdown())
    except Exception:  # noqa: BLE001
        pass
    index.close()


def test_post_start_then_stop(app_and_root) -> None:
    app, root, _recorder, _index = app_and_root
    with TestClient(app) as client:
        r = client.post(
            "/recording/start",
            json={"mission_id": "m1", "drone_id": "d1", "notes": "test"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["mission_id"] == "m1"
        assert body["drone_id"] == "d1"
        recording_id = body["recording_id"]
        assert "path" in body

        # Wait a moment for ffmpeg to write.
        import time

        time.sleep(0.2)

        # Double start -> 409.
        r2 = client.post("/recording/start", json={})
        assert r2.status_code == 409

        # Status -> active.
        rs = client.get("/recording/status")
        assert rs.status_code == 200
        assert rs.json()["active"] is True
        assert rs.json()["recording_id"] == recording_id

        # Stop.
        r = client.post("/recording/stop")
        assert r.status_code == 200
        body = r.json()
        assert body["recording_id"] == recording_id
        assert body["bytes"] > 0
        assert body["sha256"]

        # Double stop -> 409.
        r = client.post("/recording/stop")
        assert r.status_code == 409


def test_list_and_metadata_and_download(app_and_root) -> None:
    app, root, _recorder, _index = app_and_root
    with TestClient(app) as client:
        r = client.post(
            "/recording/start",
            json={"mission_id": "alpha", "drone_id": "drone-01", "notes": "field test"},
        )
        rid = r.json()["recording_id"]
        import time

        time.sleep(0.2)
        client.post("/recording/stop")

        # List.
        r = client.get("/recording/list")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["id"] == rid
        assert rows[0]["state"] == "finalized"

        # Metadata (reads sidecar + merges index).
        r = client.get(f"/recording/{rid}/metadata")
        assert r.status_code == 200
        meta = r.json()
        assert meta["recording_id"] == rid
        assert meta["mission_id"] == "alpha"

        # Download.
        r = client.get(f"/recording/{rid}/download")
        assert r.status_code == 200
        assert r.headers["content-type"] == "video/mp2t"
        assert (
            'filename="alpha_drone-01_'
            in r.headers["content-disposition"]
        )
        assert len(r.content) > 0


def test_delete_moves_to_trash(app_and_root) -> None:
    app, root, _recorder, _index = app_and_root
    with TestClient(app) as client:
        r = client.post("/recording/start", json={})
        rid = r.json()["recording_id"]
        import time

        time.sleep(0.2)
        client.post("/recording/stop")

        # Cannot delete active (this is finalized already, just a sanity check).
        r = client.delete(f"/recording/{rid}")
        assert r.status_code == 200
        result = r.json()
        assert result["state"] == "deleted"
        assert ".trash" in result["path"]

        # File actually lives in trash now.
        trash_path = Path(result["path"])
        assert trash_path.exists()

        # Default list excludes deleted.
        r = client.get("/recording/list")
        assert r.json() == []

        # With include_deleted=true, it's visible.
        r = client.get("/recording/list?include_deleted=true")
        assert len(r.json()) == 1
        assert r.json()[0]["state"] == "deleted"


def test_disk_endpoint(app_and_root) -> None:
    app, root, _recorder, _index = app_and_root
    with TestClient(app) as client:
        r = client.get("/recording/disk")
        assert r.status_code == 200
        body = r.json()
        assert body["total_bytes"] > 0
        assert body["free_bytes"] >= 0
        assert body["path"] == str(root)
        assert body["count"] == 0


def test_metadata_404(app_and_root) -> None:
    app, _root, _recorder, _index = app_and_root
    with TestClient(app) as client:
        r = client.get("/recording/does-not-exist/metadata")
        assert r.status_code == 404


def test_cannot_delete_active(app_and_root) -> None:
    app, _root, _recorder, _index = app_and_root
    with TestClient(app) as client:
        r = client.post("/recording/start", json={})
        rid = r.json()["recording_id"]
        try:
            r = client.delete(f"/recording/{rid}")
            assert r.status_code == 409
        finally:
            client.post("/recording/stop")
