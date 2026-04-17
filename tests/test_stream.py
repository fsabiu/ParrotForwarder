"""
Tests for the WebSocket streaming endpoints.

Uses FastAPI's TestClient websocket helper. No real uvicorn needed.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from parrot_forwarder.supervisor.api.stream import (
    Broadcaster,
    publish_log,
    publish_restart,
    publish_state_transition,
    register_stream_routes,
)


@pytest.fixture()
def app_and_broadcasters() -> tuple[FastAPI, Broadcaster, Broadcaster]:
    app = FastAPI()
    events = Broadcaster(max_queue=4)
    telemetry = Broadcaster(max_queue=4)
    register_stream_routes(app, events=events, telemetry=telemetry)
    return app, events, telemetry


def test_events_websocket_receives_published_frames(
    app_and_broadcasters: tuple[FastAPI, Broadcaster, Broadcaster],
) -> None:
    app, events, _ = app_and_broadcasters
    client = TestClient(app)
    with client.websocket_connect("/stream/events") as ws:
        # Subscriber is registered lazily after accept - give the server a
        # beat, then publish. TestClient runs the server in a thread so
        # this is enough.
        import time

        for _ in range(20):
            if events.subscriber_count >= 1:
                break
            time.sleep(0.01)
        assert events.subscriber_count == 1

        async def _publish() -> None:
            await publish_state_transition(
                events,
                from_state="READY",
                to_state="STREAMING",
                reason="pipeline_started",
                at="2026-04-17T00:00:00Z",
            )

        asyncio.run(_publish())
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["to"] == "STREAMING"


def test_telemetry_websocket_accepts_rate_query(
    app_and_broadcasters: tuple[FastAPI, Broadcaster, Broadcaster],
) -> None:
    app, _, telemetry = app_and_broadcasters
    client = TestClient(app)
    with client.websocket_connect("/stream/telemetry?rate=5") as ws:
        import time

        for _ in range(20):
            if telemetry.subscriber_count >= 1:
                break
            time.sleep(0.01)

        async def _publish() -> None:
            await telemetry.publish({"t": "2026-04-17T00:00:00Z", "payload": {"fps": 30}})

        asyncio.run(_publish())
        msg = ws.receive_json()
        assert msg["payload"] == {"fps": 30}


def test_telemetry_rate_is_validated(
    app_and_broadcasters: tuple[FastAPI, Broadcaster, Broadcaster],
) -> None:
    app, _, _ = app_and_broadcasters
    client = TestClient(app)
    # rate=0 violates ge=1. FastAPI rejects the connect before we ever
    # enter the WebSocket handshake proper; the TestClient surfaces this
    # as a generic WebSocket error. We just need the connect to fail.
    from starlette.websockets import WebSocketDisconnect as _WSD

    with pytest.raises((_WSD, Exception)):  # noqa: B017
        with client.websocket_connect("/stream/telemetry?rate=0"):
            pass


async def test_broadcaster_drops_slow_subscriber() -> None:
    b = Broadcaster(max_queue=2)
    q = await b.subscribe()
    assert b.subscriber_count == 1
    # Fill the queue past its cap. The third publish must disconnect the
    # subscriber rather than stall.
    for i in range(5):
        await b.publish({"i": i})
    assert b.subscriber_count == 0, "slow subscriber must be dropped"
    # Queue still holds the first max_queue items.
    assert q.qsize() == 2


async def test_broadcaster_no_subscribers_is_noop() -> None:
    b = Broadcaster()
    # Must not raise.
    await b.publish({"x": 1})


async def test_publish_log_and_restart_shape() -> None:
    b = Broadcaster()
    q = await b.subscribe()
    await publish_log(b, level="warning", message="blip", at="2026-04-17T00:00:00Z")
    await publish_restart(b, count=3, reason="pipeline_error", at="2026-04-17T00:00:01Z")
    log = q.get_nowait()
    restart = q.get_nowait()
    assert log == {
        "type": "log",
        "level": "warning",
        "message": "blip",
        "at": "2026-04-17T00:00:00Z",
    }
    assert restart == {
        "type": "restart",
        "count": 3,
        "reason": "pipeline_error",
        "at": "2026-04-17T00:00:01Z",
    }


def test_disconnect_unsubscribes(
    app_and_broadcasters: tuple[FastAPI, Broadcaster, Broadcaster],
) -> None:
    app, events, _ = app_and_broadcasters
    client = TestClient(app)
    with client.websocket_connect("/stream/events"):
        import time

        for _ in range(20):
            if events.subscriber_count >= 1:
                break
            time.sleep(0.01)
    # After the context closes, the server should have cleaned up the subscriber.
    import time

    for _ in range(20):
        if events.subscriber_count == 0:
            break
        time.sleep(0.01)
    assert events.subscriber_count == 0
