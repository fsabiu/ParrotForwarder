"""
FastAPI application for the supervisor.

Mount points mirror ``v2/architecture/api-contract.md`` and
``v2/specs/03-rest-api.md``. Error responses use RFC 7807
``application/problem+json``. A request-ID middleware stamps
every request/response for log correlation.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp

from ...dashboard import static_dir as dashboard_static_dir
from ...state_machine import UserReset, UserStart, UserStop

if TYPE_CHECKING:
    from .. import Supervisor

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


class ResetRequest(BaseModel):
    reason: str | None = None


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


def create_app(supervisor: Supervisor) -> FastAPI:
    """Build the FastAPI app wired to ``supervisor``.

    The supervisor is passed in explicitly rather than pulled from a
    global so tests can construct many instances side-by-side.
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

    app.add_exception_handler(HTTPException, _http_exception_to_problem)
    app.add_exception_handler(StarletteHTTPException, _http_exception_to_problem)
    app.add_exception_handler(Exception, _unhandled_exception_to_problem)

    _register_routes(app, supervisor)
    _register_dashboard(app)
    _register_preview_stub(app)
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
        return StatusResponse(
            state=sm.state.value,
            restarts_total=supervisor.restart_count,
            consecutive_failures=sm.backoff.consecutive_failures,
        )

    @app.get("/config", summary="Effective configuration")
    async def _config() -> dict[str, object]:
        # Config loading is the supervisor's caller's responsibility; we
        # expose only what the runtime knows about. Future tasks (T11/T12)
        # attach the full loaded config here.
        return {
            "backoff": {
                "base_seconds": supervisor.backoff_policy.base_seconds,
                "max_seconds": supervisor.backoff_policy.max_seconds,
                "jitter_seconds": supervisor.backoff_policy.jitter_seconds,
            },
            "auto_start": supervisor.auto_start,
        }

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


def make_asgi_app(supervisor: Supervisor) -> ASGIApp:
    """Return the ASGI callable for uvicorn."""
    return create_app(supervisor)


# ---------------------------------------------------------------------------
# Dashboard + preview mounts
# ---------------------------------------------------------------------------


def _register_dashboard(app: FastAPI) -> None:
    static_dir = dashboard_static_dir()
    if not static_dir.is_dir():
        return
    app.mount(
        "/assets",
        StaticFiles(directory=str(static_dir)),
        name="dashboard-assets",
    )

    @app.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(static_dir / "index.html", media_type="text/html")

    @app.get("/app.js", include_in_schema=False)
    async def _app_js() -> FileResponse:
        return FileResponse(static_dir / "app.js", media_type="application/javascript")

    @app.get("/style.css", include_in_schema=False)
    async def _style_css() -> FileResponse:
        return FileResponse(static_dir / "style.css", media_type="text/css")


def _register_preview_stub(app: FastAPI) -> None:
    """Stub the HLS preview endpoints.

    The real pipeline (GStreamer ``hlssink2`` writing to a shared directory)
    will replace these when the worker's GStreamer branch lands on a host
    with a drone. Until then we return an empty but valid HLS playlist so
    the dashboard's ``<video>`` element doesn't log noisy fetch errors.
    """

    placeholder_playlist = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXT-X-ENDLIST\n"
    )

    @app.get("/preview/stream.m3u8", include_in_schema=False)
    async def _preview_playlist() -> Response:
        return Response(
            content=placeholder_playlist,
            media_type="application/vnd.apple.mpegurl",
        )
