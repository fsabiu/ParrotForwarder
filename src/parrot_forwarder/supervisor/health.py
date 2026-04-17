"""
Health monitor - detects unhealthy-but-not-crashed worker conditions.

Reads heartbeats (with their attached ``metrics`` bag) and fires
``HealthUnresponsive`` / ``HealthDegraded`` state-machine events when
thresholds are crossed. A recovery hysteresis avoids flapping.

The monitor is driven by ``record_heartbeat`` / a periodic poll; it
does not maintain its own asyncio task, so tests can step it manually
via the injected ``now_fn``. A thin ``run()`` coroutine is provided
for the production case.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..state_machine import HealthDegraded, HealthUnresponsive, Heartbeat

logger = logging.getLogger(__name__)


def _default_now() -> float:
    """Monotonic clock. Indirected so tests can inject a fake."""
    return time.monotonic()


@dataclass(frozen=True)
class HealthThresholds:
    """Field values below which the monitor flags a signal as degraded.

    Every threshold has a meaningful default; callers typically load
    overrides from ``config.yaml``.
    """

    heartbeat_timeout_seconds: float = 5.0
    fps_min: float = 10.0
    fps_min_window_seconds: float = 5.0
    battery_percent_min: int = 10
    rssi_dbm_min: float = -85.0
    recovery_window_seconds: float = 5.0


@dataclass
class HealthMonitor:
    """Stateful watcher over heartbeat + metric streams.

    The monitor is intentionally passive - it returns events to post.
    The supervisor is responsible for calling :meth:`record_heartbeat`
    when a ``HeartbeatMsg`` lands over IPC, and :meth:`poll` periodically
    to catch heartbeat timeouts that wouldn't otherwise fire.
    """

    thresholds: HealthThresholds = field(default_factory=HealthThresholds)
    now_fn: Callable[[], float] = field(default_factory=lambda: _default_now)

    # Internal state - do not poke from outside tests.
    _last_heartbeat_at: float | None = None
    _last_seq: int | None = None
    _fps_ok_since: float | None = None
    _fps_fail_since: float | None = None
    _degraded_signals: set[str] = field(default_factory=set)
    _unresponsive_emitted: bool = False

    # ------------------------------------------------------------------
    # Public API (events-out-as-values)
    # ------------------------------------------------------------------

    def record_heartbeat(
        self, hb: Heartbeat, metrics: dict[str, float] | None = None
    ) -> list[object]:
        """Process a heartbeat. Returns state-machine events to post."""
        events: list[object] = []
        self._last_heartbeat_at = self.now_fn()
        self._last_seq = hb.seq
        if self._unresponsive_emitted:
            self._unresponsive_emitted = False

        # Metric thresholds. "metrics" defaults to an empty dict so callers
        # can omit fields they don't have.
        metrics = metrics or {}
        events.extend(self._check_fps(metrics))
        events.extend(self._check_battery(metrics))
        events.extend(self._check_rssi(metrics))
        return events

    def poll(self) -> list[object]:
        """Periodic call. Returns state-machine events to post."""
        events: list[object] = []
        if self._last_heartbeat_at is None:
            # Never received a heartbeat - the supervisor hasn't told us the
            # worker is running yet; don't fire.
            return events
        lag = self.now_fn() - self._last_heartbeat_at
        if (
            lag > self.thresholds.heartbeat_timeout_seconds
            and not self._unresponsive_emitted
        ):
            self._unresponsive_emitted = True
            events.append(HealthUnresponsive(since_seconds=lag))
        return events

    def reset(self) -> None:
        """Forget everything - useful when a worker respawn starts clean."""
        self._last_heartbeat_at = None
        self._last_seq = None
        self._fps_ok_since = None
        self._fps_fail_since = None
        self._degraded_signals.clear()
        self._unresponsive_emitted = False

    # ------------------------------------------------------------------
    # Signal checks
    # ------------------------------------------------------------------

    def _check_fps(self, metrics: dict[str, float]) -> list[object]:
        fps = metrics.get("fps")
        if fps is None:
            return []
        now = self.now_fn()
        if fps < self.thresholds.fps_min:
            # Track how long we've been below threshold.
            if self._fps_fail_since is None:
                self._fps_fail_since = now
            if (
                now - self._fps_fail_since >= self.thresholds.fps_min_window_seconds
                and "fps" not in self._degraded_signals
            ):
                self._degraded_signals.add("fps")
                self._fps_ok_since = None
                return [HealthDegraded(signal="fps")]
            return []
        # Healthy FPS again.
        self._fps_fail_since = None
        self._degraded_signals.discard("fps")
        return []

    def _check_battery(self, metrics: dict[str, float]) -> list[object]:
        battery = metrics.get("battery_percent")
        if battery is None:
            return []
        if battery < self.thresholds.battery_percent_min:
            if "battery" not in self._degraded_signals:
                self._degraded_signals.add("battery")
                return [HealthDegraded(signal="battery")]
            return []
        self._degraded_signals.discard("battery")
        return []

    def _check_rssi(self, metrics: dict[str, float]) -> list[object]:
        rssi = metrics.get("rssi_dbm")
        if rssi is None:
            return []
        if rssi < self.thresholds.rssi_dbm_min:
            if "rssi" not in self._degraded_signals:
                self._degraded_signals.add("rssi")
                return [HealthDegraded(signal="rssi")]
            return []
        self._degraded_signals.discard("rssi")
        return []


# ---------------------------------------------------------------------------
# Production driver - runs the poll loop and posts events to the supervisor.
# ---------------------------------------------------------------------------


async def run_health_poll_loop(
    monitor: HealthMonitor,
    post_event: Callable[[object], Awaitable[None]],
    interval_seconds: float = 1.0,
) -> None:
    """Tight loop that calls :meth:`HealthMonitor.poll` and posts events.

    The caller is expected to cancel this coroutine on supervisor
    shutdown. Cancellation is awaited cleanly.
    """
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            for event in monitor.poll():
                await post_event(event)
    except asyncio.CancelledError:
        return
