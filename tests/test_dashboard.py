"""
Tests for the dashboard static mount and HLS preview stub.

The dashboard itself is a plain HTML/JS bundle with no build step -
we check that every asset the ``index.html`` references is actually
served and that the HLS preview stub returns a syntactically valid
playlist so the ``<video>`` element doesn't log fetch errors.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from parrot_forwarder import ipc as ipc_module
from parrot_forwarder.supervisor import Supervisor, WorkerHandle
from parrot_forwarder.supervisor.api import create_app


class _StubWorker:
    def handle(self) -> WorkerHandle:
        exited: asyncio.Future[int] = asyncio.get_event_loop().create_future()

        async def send(_m: ipc_module._IpcBase) -> None:
            pass

        async def close() -> None:
            if not exited.done():
                exited.set_result(0)

        return WorkerHandle(pid=1, send=send, close=close, exited=exited)


@pytest.fixture()
def client() -> TestClient:
    sup = Supervisor(
        worker_factory=lambda _s: _StubWorker().handle(),  # type: ignore[arg-type]
        auto_start=False,
        sleep=lambda _s: asyncio.sleep(0),
    )
    return TestClient(create_app(sup))


def test_dashboard_index_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert "ParrotForwarder" in response.text
    assert "state-badge" in response.text  # hook-up point for JS
    assert "telemetry-json" in response.text
    assert "app.js" in response.text
    assert "style.css" in response.text


def test_dashboard_js_served(client: TestClient) -> None:
    response = client.get("/app.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "no-cache"
    assert "/control/start" in response.text, "dashboard JS must hit REST contract"
    assert "/stream/events" in response.text


def test_dashboard_css_served(client: TestClient) -> None:
    response = client.get("/style.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.headers["cache-control"] == "no-cache"


def test_preview_stream_returns_valid_m3u8(client: TestClient) -> None:
    response = client.get("/preview/stream.m3u8")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.apple.mpegurl"
    body = response.text
    assert body.startswith("#EXTM3U")
    assert "#EXT-X-ENDLIST" in body


def test_index_references_preview_m3u8(client: TestClient) -> None:
    index = client.get("/").text
    assert "/preview/stream.m3u8" in index
