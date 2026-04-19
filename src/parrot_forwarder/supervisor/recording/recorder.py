"""
Recorder: ffmpeg subprocess that captures video + KLV from the forwarder's SRT output.

Design rules:

- One active recording at a time (sprint 1 scope).
- ffmpeg is the authoritative process. We stream-copy video + data; zero
  re-encode. Stopping ffmpeg cleanly (SIGINT) is the only way to get a valid
  MPEG-TS trailer.
- The recorder is the sole writer of rows to the index except for the
  ``deleted`` state transition (driven by the API layer).
- Crash recovery runs once at init: any row left in ``active`` state is
  reconciled against the filesystem and either finalized (file exists and is
  readable) or marked ``error``.
- Callers MUST check ``is_running()`` before ``start()``; starting while
  another recording is active raises :class:`AlreadyRecordingError`.

The ffmpeg command matches the one Francesco validated manually:

    ffmpeg -hide_banner -nostdin -y -i 'srt://127.0.0.1:<port>?mode=caller' \\
        -map 0:v -map 0:d -c copy -f mpegts <out>.ts

``-map 0:d`` is what carries the KLV data stream through to disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from parrot_forwarder.supervisor.recording.index import (
    RecordingIndex,
    RecordingRow,
)

logger = logging.getLogger(__name__)


class RecorderError(Exception):
    """Base class for recorder errors."""


class AlreadyRecordingError(RecorderError):
    """Raised when ``start`` is called while another recording is active."""


class NotRecordingError(RecorderError):
    """Raised when ``stop`` is called with no active recording."""


class RecordingStartFailed(RecorderError):
    """Raised when ffmpeg fails to start (e.g. SRT source unavailable)."""


@dataclass(frozen=True)
class RecordingMeta:
    """Operator-provided metadata attached to a recording."""

    mission_id: str | None = None
    drone_id: str | None = None
    session_id: str | None = None
    notes: str | None = None
    trigger: str = "manual"  # manual | auto-takeoff | api


@dataclass(frozen=True)
class ActiveRecording:
    """View of the currently-running recording."""

    recording_id: str
    path: str
    started_at: str
    mission_id: str | None
    drone_id: str | None
    session_id: str | None
    trigger: str


@dataclass(frozen=True)
class StoppedRecording:
    """Result of a successful ``stop`` call."""

    recording_id: str
    path: str
    duration_s: int
    bytes: int
    sha256: str


EventSink = Callable[[str, dict[str, object]], Awaitable[None]]


class Recorder:
    """Owns the single active ffmpeg recording subprocess.

    Parameters
    ----------
    root_path
        The host-visible directory where files are written.
    index
        Opened :class:`RecordingIndex` used to track state.
    srt_port
        Port of the forwarder's SRT listener (127.0.0.1:srt_port).
    event_sink
        Optional async callback invoked with (event_type, payload). The
        supervisor wires this to its broadcaster so the dashboard sees
        ``recording.started`` / ``recording.stopped`` / ``recording.error``.
    ffmpeg_path
        Override for the ffmpeg binary; defaults to ``ffmpeg`` on PATH.
    fw_version
        Git hash or version tag written into sidecars for provenance.
    """

    def __init__(
        self,
        *,
        root_path: Path,
        index: RecordingIndex,
        srt_port: int,
        event_sink: EventSink | None = None,
        ffmpeg_path: str = "ffmpeg",
        fw_version: str | None = None,
    ) -> None:
        self._root = root_path
        self._index = index
        self._srt_port = srt_port
        self._event_sink = event_sink
        self._ffmpeg_path = ffmpeg_path
        self._fw_version = fw_version
        self._proc: asyncio.subprocess.Process | None = None
        self._active: ActiveRecording | None = None
        self._active_meta: RecordingMeta | None = None
        self._active_path: Path | None = None
        self._started_at_dt: datetime | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, meta: RecordingMeta) -> ActiveRecording:
        """Begin a new recording. Returns a view of the active recording."""
        async with self._lock:
            if self._proc is not None:
                raise AlreadyRecordingError("another recording is already active")

            recording_id = _new_recording_id()
            started_at = datetime.now(timezone.utc)
            rel_path = _build_relative_path(
                started_at=started_at,
                mission_id=meta.mission_id,
                drone_id=meta.drone_id,
                notes=meta.notes,
            )
            full_path = self._root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            self._index.insert_active(
                recording_id=recording_id,
                path=str(full_path),
                started_at=started_at,
                drone_id=meta.drone_id,
                session_id=meta.session_id,
                mission_id=meta.mission_id,
                notes=meta.notes,
                trigger=meta.trigger,
            )

            cmd = self._build_ffmpeg_cmd(full_path)
            logger.info("spawning recorder: %s", " ".join(cmd))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                self._index.mark_error(recording_id, f"ffmpeg not found: {exc}")
                raise RecordingStartFailed(f"ffmpeg binary missing: {exc}") from exc

            # Quick smoke: if ffmpeg exits within 500 ms, treat as failure so
            # the operator sees the error synchronously from the HTTP response
            # rather than via a later event. Slower asynchronous failures are
            # handled by the watchdog task.
            try:
                await asyncio.wait_for(proc.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass  # good, it's still running
            else:
                stderr = b""
                if proc.stderr is not None:
                    stderr = await proc.stderr.read()
                reason = stderr.decode(errors="replace").strip().splitlines()[-1:]
                reason_str = reason[0] if reason else f"ffmpeg exited rc={proc.returncode}"
                self._index.mark_error(recording_id, reason_str)
                raise RecordingStartFailed(reason_str)

            self._proc = proc
            self._active_meta = meta
            self._active_path = full_path
            self._started_at_dt = started_at
            self._active = ActiveRecording(
                recording_id=recording_id,
                path=str(full_path),
                started_at=_iso(started_at),
                mission_id=meta.mission_id,
                drone_id=meta.drone_id,
                session_id=meta.session_id,
                trigger=meta.trigger,
            )
            self._watchdog = asyncio.create_task(
                self._watch_process(recording_id, proc),
                name=f"recorder-watch:{recording_id}",
            )
            self._write_sidecar(full_path, recording_id, started_at, meta)
            await self._emit("recording.started", _active_payload(self._active))
            return self._active

    async def stop(self, *, timeout: float = 10.0) -> StoppedRecording:
        """Stop the active recording and finalize. Returns the final row summary."""
        async with self._lock:
            if self._proc is None or self._active is None:
                raise NotRecordingError("no active recording to stop")
            proc = self._proc
            active = self._active
            path = self._active_path
            started_dt = self._started_at_dt
            assert path is not None and started_dt is not None

            if proc.returncode is None:
                try:
                    proc.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning("ffmpeg did not exit after SIGINT; sending SIGTERM")
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        logger.error("ffmpeg still alive; SIGKILL")
                        proc.kill()
                        await proc.wait()

            stopped_at = datetime.now(timezone.utc)
            bytes_ = path.stat().st_size if path.exists() else 0
            sha = await asyncio.to_thread(_sha256_of, path) if path.exists() else ""
            duration_s = int((stopped_at - started_dt).total_seconds())

            self._index.finalize(
                active.recording_id,
                bytes_=bytes_,
                sha256=sha,
                stopped_at=stopped_at,
            )
            self._update_sidecar(
                path, active.recording_id, started_dt, stopped_at, bytes_, sha
            )

            result = StoppedRecording(
                recording_id=active.recording_id,
                path=str(path),
                duration_s=duration_s,
                bytes=bytes_,
                sha256=sha,
            )
            await self._emit("recording.stopped", asdict(result))

            self._proc = None
            self._active = None
            self._active_meta = None
            self._active_path = None
            self._started_at_dt = None
            if self._watchdog is not None and not self._watchdog.done():
                self._watchdog.cancel()
            self._watchdog = None
            return result

    async def shutdown(self) -> StoppedRecording | None:
        """Called on supervisor SIGTERM. Stop cleanly if recording."""
        if self._proc is None:
            return None
        try:
            return await self.stop(timeout=15.0)
        except NotRecordingError:
            return None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def status(self) -> dict[str, object]:
        if self._active is None or self._active_path is None or self._started_at_dt is None:
            return {"active": False}
        current_bytes = 0
        try:
            current_bytes = self._active_path.stat().st_size
        except OSError:
            pass
        elapsed = (datetime.now(timezone.utc) - self._started_at_dt).total_seconds()
        return {
            "active": True,
            "recording_id": self._active.recording_id,
            "path": self._active.path,
            "started_at": self._active.started_at,
            "mission_id": self._active.mission_id,
            "drone_id": self._active.drone_id,
            "session_id": self._active.session_id,
            "trigger": self._active.trigger,
            "elapsed_s": elapsed,
            "bytes": current_bytes,
        }

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def reconcile_active_rows(self) -> list[RecordingRow]:
        """Reconcile orphan ``active`` rows from a previous process.

        For each row:
        - if the file exists and is non-empty, finalize with
          ``stopped_at = file mtime`` and actual SHA256.
        - otherwise, mark as error.

        Must be called before the first ``start()``. Safe to call with an
        empty index.
        """
        reconciled: list[RecordingRow] = []
        for row in list(self._index.iter_active()):
            path = Path(row.path)
            if path.exists() and path.stat().st_size > 0:
                stopped_at = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
                sha = _sha256_of(path)
                self._index.finalize(
                    row.id,
                    bytes_=path.stat().st_size,
                    sha256=sha,
                    stopped_at=stopped_at,
                )
                reconciled.append(row)
                logger.warning(
                    "reconciled orphan recording %s -> finalized (mtime=%s)",
                    row.id,
                    stopped_at.isoformat(),
                )
            else:
                self._index.mark_error(row.id, "crash: file missing or empty at restart")
                reconciled.append(row)
                logger.warning(
                    "reconciled orphan recording %s -> error (no file)", row.id
                )
        return reconciled

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_ffmpeg_cmd(self, out_path: Path) -> list[str]:
        url = f"srt://127.0.0.1:{self._srt_port}?mode=caller"
        return [
            self._ffmpeg_path,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            url,
            "-map",
            "0:v",
            "-map",
            "0:d",
            "-c",
            "copy",
            "-f",
            "mpegts",
            str(out_path),
        ]

    async def _watch_process(
        self, recording_id: str, proc: asyncio.subprocess.Process
    ) -> None:
        """Wait on the ffmpeg process; if it exits while we think the recording is
        active, mark as error and emit an event."""
        rc = await proc.wait()
        # If stop() has already cleared self._proc, this is a normal exit.
        if self._proc is not proc:
            return
        stderr = b""
        if proc.stderr is not None:
            try:
                stderr = await proc.stderr.read()
            except Exception:  # noqa: BLE001
                stderr = b""
        reason_lines = stderr.decode(errors="replace").strip().splitlines()
        reason = reason_lines[-1] if reason_lines else f"ffmpeg exited rc={rc}"
        logger.error("recorder %s crashed: rc=%s reason=%s", recording_id, rc, reason)
        self._index.mark_error(recording_id, reason)
        await self._emit(
            "recording.error",
            {"recording_id": recording_id, "rc": rc, "reason": reason},
        )
        self._proc = None
        self._active = None
        self._active_meta = None
        self._active_path = None
        self._started_at_dt = None

    def _write_sidecar(
        self,
        path: Path,
        recording_id: str,
        started_at: datetime,
        meta: RecordingMeta,
    ) -> None:
        sidecar = path.with_suffix(".meta.json")
        payload = {
            "recording_id": recording_id,
            "started_at": _iso(started_at),
            "stopped_at": None,
            "duration_s": None,
            "bytes": None,
            "sha256": None,
            "mission_id": meta.mission_id,
            "drone_id": meta.drone_id,
            "session_id": meta.session_id,
            "notes": meta.notes,
            "trigger": meta.trigger,
            "srt_source": f"srt://127.0.0.1:{self._srt_port}",
            "fw_version": self._fw_version,
        }
        _atomic_write_json(sidecar, payload)

    def _update_sidecar(
        self,
        path: Path,
        recording_id: str,
        started_at: datetime,
        stopped_at: datetime,
        bytes_: int,
        sha: str,
    ) -> None:
        sidecar = path.with_suffix(".meta.json")
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"recording_id": recording_id, "started_at": _iso(started_at)}
        payload.update(
            {
                "stopped_at": _iso(stopped_at),
                "duration_s": int((stopped_at - started_at).total_seconds()),
                "bytes": bytes_,
                "sha256": sha,
            }
        )
        _atomic_write_json(sidecar, payload)

    async def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self._event_sink is None:
            return
        try:
            await self._event_sink(event_type, payload)
        except Exception:  # noqa: BLE001
            logger.exception("event sink failed for %s", event_type)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_recording_id() -> str:
    return uuid.uuid4().hex


def _build_relative_path(
    *,
    started_at: datetime,
    mission_id: str | None,
    drone_id: str | None,
    notes: str | None,
) -> Path:
    date_part = started_at.strftime("%Y-%m-%d")
    mission = _safe_segment(mission_id) if mission_id else "default"
    drone = _safe_segment(drone_id) if drone_id else "drone"
    note = _safe_segment(notes) if notes else None
    iso_compact = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    filename_parts = [mission, drone]
    if note:
        filename_parts.append(note)
    filename_parts.append(iso_compact)
    filename = "_".join(filename_parts) + ".ts"
    return Path(date_part) / mission / filename


def _safe_segment(raw: str) -> str:
    """Make a filesystem-safe path segment."""
    out = []
    for ch in raw:
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_") or "unknown"


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _active_payload(active: ActiveRecording) -> dict[str, object]:
    return {
        "recording_id": active.recording_id,
        "path": active.path,
        "started_at": active.started_at,
        "mission_id": active.mission_id,
        "drone_id": active.drone_id,
        "session_id": active.session_id,
        "trigger": active.trigger,
    }
