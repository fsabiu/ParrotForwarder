"""
WebSocket streams for events and telemetry.

Two endpoints:

  * ``/stream/events``     - state transitions + notable logs.
  * ``/stream/telemetry``  - decoded telemetry at ``?rate=<hz>``.

Each stream is a small pub-sub hub: the supervisor publishes into a
``Broadcaster`` and every connected WebSocket client reads from its own
bounded ``asyncio.Queue``. Slow consumers are detected by queue-full
conditions and disconnected rather than allowed to back up the publisher.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Broadcaster
# ---------------------------------------------------------------------------


@dataclass
class Broadcaster:
    """One-to-many fan-out over bounded per-subscriber queues.

    Attributes:
        max_queue: Hard cap per subscriber. A full queue means the
            subscriber is slower than the publisher; we drop that
            subscriber rather than letting them stall the publisher.
    """

    max_queue: int = 128
    _subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.max_queue)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, message: dict[str, Any]) -> None:
        """Broadcast ``message`` to every subscriber.

        Returns immediately if there are no subscribers. A subscriber
        whose queue is full is disconnected by dropping its reference;
        the WebSocket handler will notice the dropped queue on its next
        ``get()`` and close the connection.
        """
        async with self._lock:
            targets = list(self._subscribers)
        for queue in targets:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("dropping slow subscriber: queue full")
                await self.unsubscribe(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------


def register_stream_routes(
    app: FastAPI,
    *,
    events: Broadcaster,
    telemetry: Broadcaster,
    default_telemetry_rate_hz: int = 30,
    max_telemetry_rate_hz: int = 100,
) -> None:
    """Attach ``/stream/events`` and ``/stream/telemetry`` to ``app``."""

    @app.websocket("/stream/events")
    async def _events_ws(ws: WebSocket) -> None:
        await _serve(ws, events)

    @app.websocket("/stream/telemetry")
    async def _telemetry_ws(
        ws: WebSocket,
        rate: int | None = Query(
            default=None,
            ge=1,
            le=max_telemetry_rate_hz,
            description="Max Hz",
        ),
    ) -> None:
        rate_hz = rate or _configured_telemetry_rate_hz(
            app,
            default_rate_hz=default_telemetry_rate_hz,
            max_rate_hz=max_telemetry_rate_hz,
        )
        await _serve(ws, telemetry, rate_hz=rate_hz)


def _configured_telemetry_rate_hz(
    app: FastAPI,
    *,
    default_rate_hz: int,
    max_rate_hz: int,
) -> int:
    cfg = getattr(app.state, "config", None)
    try:
        value = int(cfg.forwarder.telemetry_fps) if cfg is not None else default_rate_hz
    except (AttributeError, TypeError, ValueError):
        value = default_rate_hz
    return max(1, min(max_rate_hz, value))


async def _serve(
    ws: WebSocket,
    broadcaster: Broadcaster,
    *,
    rate_hz: int | None = None,
) -> None:
    """Generic WebSocket serve loop.

    If ``rate_hz`` is given, a minimum inter-message interval is enforced
    by dropping intermediate samples.
    """
    await ws.accept()
    queue = await broadcaster.subscribe()
    last_emitted = 0.0
    min_interval = 1.0 / rate_hz if rate_hz else 0.0
    try:
        while True:
            message = await queue.get()
            now = asyncio.get_event_loop().time()
            if min_interval and (now - last_emitted) < min_interval:
                continue
            last_emitted = now
            await ws.send_json(message)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("stream handler raised; closing")
        try:
            await ws.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
    finally:
        await broadcaster.unsubscribe(queue)


# ---------------------------------------------------------------------------
# Publisher helpers used by the supervisor
# ---------------------------------------------------------------------------


async def publish_state_transition(
    broadcaster: Broadcaster,
    *,
    from_state: str,
    to_state: str,
    reason: str,
    at: str,
) -> None:
    await broadcaster.publish(
        {
            "type": "state",
            "from": from_state,
            "to": to_state,
            "reason": reason,
            "at": at,
        }
    )


async def publish_restart(
    broadcaster: Broadcaster,
    *,
    count: int,
    reason: str,
    at: str,
) -> None:
    await broadcaster.publish(
        {"type": "restart", "count": count, "reason": reason, "at": at}
    )


async def publish_log(
    broadcaster: Broadcaster,
    *,
    level: str,
    message: str,
    at: str,
) -> None:
    await broadcaster.publish(
        {"type": "log", "level": level, "message": message, "at": at}
    )
