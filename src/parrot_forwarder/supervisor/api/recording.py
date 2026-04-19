"""
FastAPI router for the recording subsystem.

Routes:

    POST    /recording/start             {mission_id, drone_id, session_id, notes, trigger}
    POST    /recording/stop
    GET     /recording/status
    GET     /recording/list
    GET     /recording/disk
    GET     /recording/{id}/metadata
    GET     /recording/{id}/download
    DELETE  /recording/{id}               (soft delete, moves to .trash/)

Static paths (status, list, disk) are declared before the ``{recording_id}``
wildcard so FastAPI matches them first.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, status as http_status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from parrot_forwarder.supervisor.recording.index import (
    RecordingIndex,
    RecordingRow,
    RecordingState,
)
from parrot_forwarder.supervisor.recording.recorder import (
    AlreadyRecordingError,
    NotRecordingError,
    Recorder,
    RecordingMeta,
    RecordingStartFailed,
)

logger = logging.getLogger(__name__)


class RecordingStartRequest(BaseModel):
    mission_id: str | None = None
    drone_id: str | None = None
    session_id: str | None = None
    notes: str | None = None
    trigger: str = Field(default="manual", pattern=r"^(manual|auto-takeoff|api)$")


def _row_to_dict(row: RecordingRow) -> dict[str, object]:
    return {
        "id": row.id,
        "path": row.path,
        "started_at": row.started_at,
        "stopped_at": row.stopped_at,
        "duration_s": row.duration_s,
        "bytes": row.bytes,
        "sha256": row.sha256,
        "state": row.state,
        "drone_id": row.drone_id,
        "session_id": row.session_id,
        "mission_id": row.mission_id,
        "notes": row.notes,
        "trigger": row.trigger,
        "error_reason": row.error_reason,
    }


def create_recording_router(
    recorder: Recorder,
    index: RecordingIndex,
    root: Path,
) -> APIRouter:
    router = APIRouter(prefix="/recording", tags=["recording"])

    @router.post("/start", status_code=http_status.HTTP_201_CREATED)
    async def start(body: RecordingStartRequest) -> dict[str, object]:
        try:
            active = await recorder.start(
                RecordingMeta(
                    mission_id=body.mission_id,
                    drone_id=body.drone_id,
                    session_id=body.session_id,
                    notes=body.notes,
                    trigger=body.trigger,
                )
            )
        except AlreadyRecordingError as exc:
            raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc))
        except RecordingStartFailed as exc:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        return {
            "recording_id": active.recording_id,
            "path": active.path,
            "started_at": active.started_at,
            "mission_id": active.mission_id,
            "drone_id": active.drone_id,
            "session_id": active.session_id,
            "trigger": active.trigger,
        }

    @router.post("/stop")
    async def stop() -> dict[str, object]:
        try:
            result = await recorder.stop()
        except NotRecordingError as exc:
            raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc))
        return {
            "recording_id": result.recording_id,
            "path": result.path,
            "duration_s": result.duration_s,
            "bytes": result.bytes,
            "sha256": result.sha256,
        }

    @router.get("/status")
    async def status_endpoint() -> dict[str, object]:
        return recorder.status()

    @router.get("/list")
    async def list_recordings(
        state: RecordingState | None = None,
        mission: str | None = None,
        limit: int = 100,
        include_deleted: bool = False,
    ) -> list[dict[str, object]]:
        rows = index.list(state=state, mission_id=mission, limit=limit)
        if state is None and not include_deleted:
            rows = [r for r in rows if r.state != "deleted"]
        return [_row_to_dict(r) for r in rows]

    @router.get("/disk")
    async def disk() -> dict[str, object]:
        try:
            usage = index.disk_usage(root)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=f"recordings path missing: {exc}")
        return {
            "path": str(root),
            "used_bytes": usage.used_bytes,
            "free_bytes": usage.free_bytes,
            "total_bytes": usage.total_bytes,
            "count": usage.count,
        }

    @router.get("/{recording_id}/metadata")
    async def metadata(recording_id: str) -> dict[str, object]:
        row = index.get(recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"recording {recording_id} not found")
        sidecar_path = Path(row.path).with_suffix(".meta.json")
        if sidecar_path.exists():
            try:
                data = json.loads(sidecar_path.read_text(encoding="utf-8"))
                data["_index"] = _row_to_dict(row)
                return data
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("sidecar read failed for %s: %s", recording_id, exc)
        return _row_to_dict(row)

    @router.get("/{recording_id}/download")
    async def download(recording_id: str) -> FileResponse:
        row = index.get(recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"recording {recording_id} not found")
        path = Path(row.path)
        if not path.exists():
            raise HTTPException(status_code=410, detail=f"file missing on disk: {path}")
        return FileResponse(
            path,
            media_type="video/mp2t",
            filename=_download_filename(row, path),
            headers={"Cache-Control": "no-store"},
        )

    @router.delete("/{recording_id}")
    async def delete_recording(recording_id: str) -> dict[str, object]:
        row = index.get(recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"recording {recording_id} not found")
        if row.state == "active":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="recording is still active; stop it first",
            )
        trash_dir = root / ".trash" / recording_id
        trash_dir.mkdir(parents=True, exist_ok=True)
        old_path = Path(row.path)
        new_path = trash_dir / old_path.name
        try:
            if old_path.exists():
                old_path.rename(new_path)
            old_sidecar = old_path.with_suffix(".meta.json")
            if old_sidecar.exists():
                old_sidecar.rename(trash_dir / old_sidecar.name)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"soft-delete failed: {exc}")
        index.soft_delete(recording_id, str(new_path))
        return {"recording_id": recording_id, "path": str(new_path), "state": "deleted"}

    return router


def _download_filename(row: RecordingRow, path: Path) -> str:
    mission = _safe_segment(row.mission_id) if row.mission_id else None
    drone = _safe_segment(row.drone_id) if row.drone_id else None
    session = _safe_segment(row.session_id) if row.session_id else None
    started = _started_at_compact(row.started_at)

    parts = [part for part in (mission, drone, session, started) if part]
    if not parts:
        return path.name
    return "_".join(parts) + path.suffix


def _safe_segment(raw: str) -> str:
    chars: list[str] = []
    for ch in raw:
        if ch.isalnum() or ch in "-_.":
            chars.append(ch)
        else:
            chars.append("_")
    return "".join(chars).strip("_") or "unknown"


def _started_at_compact(started_at: str | None) -> str | None:
    if not started_at:
        return None
    try:
        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H-%M-%SZ")
