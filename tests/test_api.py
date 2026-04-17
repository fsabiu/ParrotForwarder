"""
REST API tests against an in-process supervisor (fake worker factory).

Uses FastAPI's ``TestClient`` so we don't need uvicorn running.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from parrot_forwarder import ipc as ipc_module
from parrot_forwarder.state_machine import State
from parrot_forwarder.supervisor import Supervisor, WorkerHandle
from parrot_forwarder.supervisor.api import REQUEST_ID_HEADER, create_app


class _FakeWorker:
    def __init__(self) -> None:
        self.exited: asyncio.Future[int] = asyncio.get_event_loop().create_future()
        self.closed = False

    def handle(self) -> WorkerHandle:
        async def send(_m: ipc_module._IpcBase) -> None:
            pass

        async def close() -> None:
            self.closed = True
            if not self.exited.done():
                self.exited.set_result(0)

        return WorkerHandle(pid=1234, send=send, close=close, exited=self.exited)


def _workers_factory(record: list[_FakeWorker]):
    async def _factory(_sup: Supervisor) -> WorkerHandle:
        w = _FakeWorker()
        record.append(w)
        return w.handle()

    return _factory


@pytest.fixture()
async def supervisor() -> Supervisor:
    sup = Supervisor(
        worker_factory=_workers_factory(record=[]),
        auto_start=False,
        sleep=lambda _s: asyncio.sleep(0),
    )
    return sup


@pytest.fixture()
def client(supervisor: Supervisor) -> TestClient:
    app = create_app(supervisor)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health / Status / Config
# ---------------------------------------------------------------------------


async def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_stamps_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert REQUEST_ID_HEADER in response.headers
    assert len(response.headers[REQUEST_ID_HEADER]) > 0


async def test_health_echoes_caller_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: "my-id-123"})
    assert response.headers[REQUEST_ID_HEADER] == "my-id-123"


async def test_status_exposes_current_state(
    supervisor: Supervisor, client: TestClient
) -> None:
    response = client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "DISCONNECTED"
    assert body["consecutive_failures"] == 0


async def test_config_endpoint_returns_backoff_shape(client: TestClient) -> None:
    response = client.get("/config")
    assert response.status_code == 200
    body = response.json()
    assert "backoff" in body
    assert body["backoff"]["base_seconds"] > 0
    assert "auto_start" in body


# ---------------------------------------------------------------------------
# Control endpoints
# ---------------------------------------------------------------------------


async def test_control_start_accepts_and_returns_state(
    supervisor: Supervisor, client: TestClient
) -> None:
    response = client.post("/control/start")
    assert response.status_code == 202
    body = response.json()
    assert "state" in body


async def test_control_stop_accepts(client: TestClient) -> None:
    response = client.post("/control/stop")
    assert response.status_code == 202


async def test_control_reset_accepts_with_reason(client: TestClient) -> None:
    response = client.post("/control/reset", json={"reason": "manual test"})
    assert response.status_code == 202
    body = response.json()
    assert body["reason"] == "manual test"


async def test_control_reset_accepts_without_body(client: TestClient) -> None:
    response = client.post("/control/reset")
    assert response.status_code == 202


# ---------------------------------------------------------------------------
# Error handling: RFC 7807 shape
# ---------------------------------------------------------------------------


async def test_404_returns_problem_json(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert "title" in body
    assert body["instance"].endswith("/nope")


async def test_validation_error_on_reset() -> None:
    # Reset accepts an optional reason; an invalid body type is rejected.
    sup = Supervisor(
        worker_factory=_workers_factory(record=[]),
        auto_start=False,
        sleep=lambda _s: asyncio.sleep(0),
    )
    client = TestClient(create_app(sup))
    response = client.post("/control/reset", json={"reason": 123})  # wrong type
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# End-to-end: API drives the state machine
# ---------------------------------------------------------------------------


async def test_control_start_transitions_state_via_supervisor() -> None:
    workers: list[_FakeWorker] = []
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        auto_start=False,
        sleep=lambda _s: asyncio.sleep(0),
    )
    client = TestClient(create_app(sup))
    run_task = asyncio.create_task(sup.run())
    try:
        response = client.post("/control/start")
        assert response.status_code == 202
        # Poll until the supervisor picks up the event.
        for _ in range(50):
            if sup.state_machine.state == State.CONNECTING:
                break
            await asyncio.sleep(0.02)
        assert sup.state_machine.state == State.CONNECTING
        assert len(workers) == 1
    finally:
        sup.stop()
        await asyncio.wait_for(run_task, timeout=1.0)


async def test_unhandled_exception_routes_to_problem_json(supervisor: Supervisor) -> None:
    """An exception inside a route must surface as problem+json."""
    from fastapi import FastAPI

    def _extra_routes(app: FastAPI) -> None:
        @app.get("/boom")
        async def _boom() -> dict[str, str]:
            raise RuntimeError("deliberate failure")

    app = create_app(supervisor)
    _extra_routes(app)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["detail"] == "deliberate failure"


# ---------------------------------------------------------------------------
# Smoke checks
# ---------------------------------------------------------------------------


async def test_openapi_exposed(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    doc: dict[str, Any] = response.json()
    paths = doc.get("paths", {})
    for expected in ("/health", "/status", "/config", "/control/start", "/control/stop", "/control/reset"):
        assert expected in paths, f"missing {expected} in OpenAPI"
