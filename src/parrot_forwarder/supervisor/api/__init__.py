"""
FastAPI application for the supervisor.

Mount points mirror ``v2/architecture/api-contract.md`` and
``v2/specs/03-rest-api.md``. Error responses use RFC 7807
``application/problem+json``. A request-ID middleware stamps
every request/response for log correlation.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp

from ...dashboard import static_dir as dashboard_static_dir
from ...state_machine import UserReset, UserStart, UserStop
from .recording import create_recording_router

if TYPE_CHECKING:
    from pathlib import Path as _Path

    from ...config import Config
    from .. import Supervisor
    from ..recording.index import RecordingIndex
    from ..recording.recorder import Recorder

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = Field(default="ok")


class StatusResponse(BaseModel):
    state: str
    restarts_total: int = 0
    consecutive_failures: int = 0
    runtime: dict[str, object] = Field(default_factory=dict)


class ResetRequest(BaseModel):
    reason: str | None = None


class TelemetryFpsUpdateRequest(BaseModel):
    telemetry_fps: int = Field(ge=1, le=100)


class TelemetryFpsUpdateResponse(BaseModel):
    telemetry_fps: int
    previous_telemetry_fps: int | None = None
    restart_requested: bool = False
    state: str
    message: str


class Problem(BaseModel):
    """RFC 7807 problem+json body."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    supervisor: Supervisor,
    config: Config | None = None,
    *,
    set_telemetry_fps: Callable[[int], Config] | None = None,
    recorder: Recorder | None = None,
    recording_index: RecordingIndex | None = None,
    recordings_root: _Path | None = None,
) -> FastAPI:
    """Build the FastAPI app wired to ``supervisor``.

    The supervisor is passed in explicitly rather than pulled from a
    global so tests can construct many instances side-by-side. ``config``
    is optional for unit tests; when omitted the live MJPEG preview is
    disabled and ``/preview/stream.mjpg`` returns 503.

    If ``recorder``, ``recording_index`` and ``recordings_root`` are all
    supplied, the recording endpoints are mounted under ``/recording``.
    Tests that do not exercise recording can omit them.
    """
    app = FastAPI(
        title="ParrotForwarder Supervisor",
        version="2.0.0",
        docs_url="/docs",
        redoc_url=None,
    )

    # CORS is intentionally permissive for 127.0.0.1 only - binding the
    # server to 127.0.0.1 is the security boundary for v2.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.middleware("http")(_request_id_middleware)
    app.state.config = config
    app.state.set_telemetry_fps = set_telemetry_fps
    app.state.recorder = recorder

    app.add_exception_handler(HTTPException, _http_exception_to_problem)
    app.add_exception_handler(StarletteHTTPException, _http_exception_to_problem)
    app.add_exception_handler(Exception, _unhandled_exception_to_problem)

    _register_routes(app, supervisor)
    _register_dashboard(app)
    _register_preview(app, config)
    if recorder is not None and recording_index is not None and recordings_root is not None:
        app.include_router(
            create_recording_router(recorder, recording_index, recordings_root)
        )
    return app


# ---------------------------------------------------------------------------
# Middleware and exception handlers
# ---------------------------------------------------------------------------


async def _request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[JSONResponse]],
) -> JSONResponse:
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def _http_exception_to_problem(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, (HTTPException, StarletteHTTPException)), (
        "handler registered for HTTPException only"
    )
    title = exc.detail if isinstance(exc.detail, str) else "http error"
    detail = exc.detail if isinstance(exc.detail, str) else None
    body = Problem(
        title=title,
        status=exc.status_code,
        detail=detail,
        instance=str(request.url),
    ).model_dump()
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        media_type="application/problem+json",
    )


def _unhandled_exception_to_problem(request: Request, exc: Exception) -> JSONResponse:
    body = Problem(
        title="internal server error",
        status=500,
        detail=str(exc),
        instance=str(request.url),
    ).model_dump()
    return JSONResponse(
        status_code=500,
        content=body,
        media_type="application/problem+json",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _register_routes(app: FastAPI, supervisor: Supervisor) -> None:
    @app.get("/health", response_model=HealthResponse, summary="Liveness")
    async def _health() -> HealthResponse:
        return HealthResponse()

    @app.get("/status", response_model=StatusResponse, summary="Current state snapshot")
    async def _status() -> StatusResponse:
        sm = supervisor.state_machine
        cfg = cast("Config | None", getattr(app.state, "config", None))
        recorder = getattr(app.state, "recorder", None)
        runtime: dict[str, object] = {}
        if cfg is not None:
            runtime["forwarder"] = {
                "telemetry_fps": cfg.forwarder.telemetry_fps,
                "video_fps": cfg.forwarder.video_fps,
                "srt_port": cfg.forwarder.srt_port,
                "klv_port": cfg.forwarder.klv_port,
            }
            runtime["field"] = {
                "advertised_srt_host": cfg.field.advertised_srt_host,
                "advertised_srt_port": cfg.field.advertised_srt_port,
                "advertised_dashboard_host": cfg.field.advertised_dashboard_host,
                "advertised_dashboard_port": cfg.field.advertised_dashboard_port,
                "tailscale_host": cfg.field.tailscale_host,
            }
        latest_metrics = getattr(app.state, "latest_heartbeat_metrics", None)
        if isinstance(latest_metrics, dict):
            runtime["latest_heartbeat_metrics"] = latest_metrics
        if recorder is not None and hasattr(recorder, "status"):
            runtime["recording"] = recorder.status()
        return StatusResponse(
            state=sm.state.value,
            restarts_total=supervisor.restart_count,
            consecutive_failures=sm.backoff.consecutive_failures,
            runtime=runtime,
        )

    @app.get("/config", summary="Effective configuration")
    async def _config() -> dict[str, object]:
        cfg = cast("Config | None", getattr(app.state, "config", None))
        if cfg is not None:
            return cast(dict[str, object], cfg.model_dump(mode="json"))

        # Unit-test fallback when create_app is intentionally called without
        # the runtime config object.
        return {
            "backoff": {
                "base_seconds": supervisor.backoff_policy.base_seconds,
                "max_seconds": supervisor.backoff_policy.max_seconds,
                "jitter_seconds": supervisor.backoff_policy.jitter_seconds,
            },
            "auto_start": supervisor.auto_start,
        }

    @app.put(
        "/config/forwarder/telemetry-fps",
        response_model=TelemetryFpsUpdateResponse,
        summary="Update telemetry/KLV target rate and reset the worker if active",
    )
    async def _set_telemetry_fps(body: TelemetryFpsUpdateRequest) -> TelemetryFpsUpdateResponse:
        cfg = cast("Config | None", getattr(app.state, "config", None))
        setter = cast(
            "Callable[[int], Config] | None",
            getattr(app.state, "set_telemetry_fps", None),
        )
        if cfg is None and setter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="runtime configuration is not attached",
            )

        previous = cfg.forwarder.telemetry_fps if cfg is not None else None
        if setter is not None:
            cfg = setter(body.telemetry_fps)
        else:
            assert cfg is not None
            next_forwarder = cfg.forwarder.model_copy(update={"telemetry_fps": body.telemetry_fps})
            cfg = cfg.model_copy(update={"forwarder": next_forwarder})
        app.state.config = cfg

        state_name = supervisor.state_machine.state.value
        changed = previous != body.telemetry_fps
        restart_requested = changed and state_name != "DISCONNECTED"
        if restart_requested:
            await supervisor.post_event(
                UserReset(reason=f"telemetry_fps changed to {body.telemetry_fps} Hz")
            )

        return TelemetryFpsUpdateResponse(
            telemetry_fps=body.telemetry_fps,
            previous_telemetry_fps=previous,
            restart_requested=restart_requested,
            state=state_name,
            message=(
                "telemetry_fps updated; worker reset requested"
                if restart_requested
                else "telemetry_fps updated"
            ),
        )

    @app.post(
        "/control/start",
        status_code=status.HTTP_202_ACCEPTED,
        summary="Start forwarding (idempotent)",
    )
    async def _start() -> dict[str, str]:
        if not supervisor.start_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="worker backend disabled on this host",
            )
        await supervisor.post_event(UserStart())
        return {"state": supervisor.state_machine.state.value}

    @app.post(
        "/control/stop",
        status_code=status.HTTP_202_ACCEPTED,
        summary="Stop forwarding; do not auto-restart",
    )
    async def _stop() -> dict[str, str]:
        await supervisor.post_event(UserStop())
        return {"state": supervisor.state_machine.state.value}

    @app.post(
        "/control/reset",
        status_code=status.HTTP_202_ACCEPTED,
        summary="Force a restart cycle",
    )
    async def _reset(body: ResetRequest | None = None) -> dict[str, str]:
        reason = (body.reason if body else None) or "operator requested"
        await supervisor.post_event(UserReset(reason=reason))
        return {"state": supervisor.state_machine.state.value, "reason": reason}


# ---------------------------------------------------------------------------
# ASGI entry point exposed for uvicorn in-process
# ---------------------------------------------------------------------------


def make_asgi_app(
    supervisor: Supervisor,
    config: Config | None = None,
    *,
    set_telemetry_fps: Callable[[int], Config] | None = None,
) -> ASGIApp:
    """Return the ASGI callable for uvicorn."""
    return create_app(supervisor, config, set_telemetry_fps=set_telemetry_fps)


# ---------------------------------------------------------------------------
# Dashboard + preview mounts
# ---------------------------------------------------------------------------


def _register_dashboard(app: FastAPI) -> None:
    static_dir = dashboard_static_dir()
    if not static_dir.is_dir():
        return
    no_cache = {"Cache-Control": "no-cache"}
    app.mount(
        "/assets",
        StaticFiles(directory=str(static_dir)),
        name="dashboard-assets",
    )

    @app.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(
            static_dir / "index.html",
            media_type="text/html",
            headers=no_cache,
        )

    @app.get("/app.js", include_in_schema=False)
    async def _app_js() -> FileResponse:
        return FileResponse(
            static_dir / "app.js",
            media_type="application/javascript",
            headers=no_cache,
        )

    @app.get("/style.css", include_in_schema=False)
    async def _style_css() -> FileResponse:
        return FileResponse(
            static_dir / "style.css",
            media_type="text/css",
            headers=no_cache,
        )


_MJPEG_BOUNDARY = "pf-frame"


def _build_mjpeg_pipeline(rtsp_url: str) -> list[str]:
    """Shell loop that respawns gst-launch if it dies (e.g. RTSP drop/EOS).

    Software H.264 decode (avdec_h264): VM has no GPU and GStreamer Vulkan
    auto-discovery is broken on the host. Frames are scaled to 640x360 and
    JPEG-encoded at quality 65 for modest CPU/bandwidth with sub-second lag.

    The shell wrapper is critical: rtspsrc on ANAFI sometimes emits EOS
    when the drone's video source momentarily pauses (e.g. gimbal recalibrates
    or camera settings change). Without a respawn the MJPEG browser stream
    would freeze until a manual reload. With ``while true`` the pipeline
    restarts and the client sees fresh multipart parts within ~1 s. Same
    boundary string across restarts keeps browsers happy.
    """
    gst_cmd = (
        "/usr/bin/gst-launch-1.0 -q "
        f"rtspsrc location='{rtsp_url}' protocols=udp latency=50 "
        "timeout=5000000 retry=3 ! "
        "rtph264depay ! h264parse ! avdec_h264 ! "
        "videoconvert ! videoscale ! video/x-raw,width=640,height=360 ! "
        "jpegenc quality=65 ! "
        f"multipartmux boundary={_MJPEG_BOUNDARY} ! "
        "fdsink fd=1"
    )
    wrapper = (
        "trap 'kill -TERM $GPID 2>/dev/null; exit 0' TERM INT; "
        "while true; do "
        f"  {gst_cmd} & GPID=$!; "
        "  wait $GPID; "
        "  echo 'mjpeg gst exited, respawning' 1>&2; "
        "  sleep 1; "
        "done"
    )
    return ["/bin/bash", "-c", wrapper]


def _register_preview(app: FastAPI, config: Config | None) -> None:
    """Live MJPEG preview pulled from the drone RTSP stream.

    Replaces the previous HLS stub. One subprocess per HTTP client; killed
    on disconnect. Trade-off: if N dashboard tabs open, N concurrent
    RTSP sessions hit the drone (Anafi tolerates a handful).
    """
    drone_ip = config.drone.ip if config is not None else None

    @app.get("/preview/stream.mjpg", include_in_schema=False)
    async def _preview_mjpeg(request: Request) -> StreamingResponse:
        if drone_ip is None:
            raise HTTPException(status_code=503, detail="preview disabled (no config)")

        rtsp_url = f"rtsp://{drone_ip}/live"
        cmd = _build_mjpeg_pipeline(rtsp_url)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"gst-launch missing: {exc}") from exc

        async def stream_body() -> AsyncIterator[bytes]:
            assert proc.stdout is not None
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    chunk = await proc.stdout.read(16384)
                    if not chunk:
                        break
                    yield chunk
            finally:
                if proc.returncode is None:
                    try:
                        proc.terminate()
                        await asyncio.wait_for(proc.wait(), timeout=2)
                    except TimeoutError:
                        proc.kill()
                    except Exception:
                        pass

        return StreamingResponse(
            stream_body(),
            media_type=f"multipart/x-mixed-replace; boundary={_MJPEG_BOUNDARY}",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Backwards-compat: dashboard cached browsers may still poll the old
    # m3u8 path. Return 410 so they stop trying.
    @app.get("/preview/stream.m3u8", include_in_schema=False)
    async def _preview_playlist_gone() -> Response:
        return Response(status_code=410, content="HLS replaced by /preview/stream.mjpg\n")
