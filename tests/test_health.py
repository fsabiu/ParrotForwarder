"""
Unit tests for the health monitor.

Fake clock - tests step ``now`` manually via ``monitor.now_fn``
rebinding. Never wall-sleep.
"""

from __future__ import annotations

import pytest

from parrot_forwarder.state_machine import HealthDegraded, HealthUnresponsive, Heartbeat
from parrot_forwarder.supervisor.health import HealthMonitor, HealthThresholds


class _FakeClock:
    """Rebindable ``now_fn`` driven by tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def advance(self, seconds: float) -> None:
        self.t += seconds

    def now(self) -> float:
        return self.t


@pytest.fixture()
def clock() -> _FakeClock:
    return _FakeClock()


@pytest.fixture()
def monitor(clock: _FakeClock) -> HealthMonitor:
    return HealthMonitor(now_fn=clock.now)


# ---------------------------------------------------------------------------
# Heartbeat timeout
# ---------------------------------------------------------------------------


def test_no_heartbeat_yet_is_silent(monitor: HealthMonitor) -> None:
    assert monitor.poll() == []


def test_heartbeat_timeout_fires_once(monitor: HealthMonitor, clock: _FakeClock) -> None:
    monitor.record_heartbeat(Heartbeat(seq=1))
    assert monitor.poll() == []
    clock.advance(6.0)  # over the 5 s threshold
    events = monitor.poll()
    assert len(events) == 1
    assert isinstance(events[0], HealthUnresponsive)
    # Subsequent polls without a fresh heartbeat must not re-fire.
    assert monitor.poll() == []


def test_fresh_heartbeat_after_timeout_resets(
    monitor: HealthMonitor, clock: _FakeClock
) -> None:
    monitor.record_heartbeat(Heartbeat(seq=1))
    clock.advance(6.0)
    assert monitor.poll()  # fires once
    clock.advance(1.0)
    monitor.record_heartbeat(Heartbeat(seq=2))
    # Still within the timeout relative to seq=2.
    assert monitor.poll() == []
    # Let the threshold elapse again - must fire a fresh event.
    clock.advance(6.0)
    events = monitor.poll()
    assert len(events) == 1


# ---------------------------------------------------------------------------
# FPS threshold
# ---------------------------------------------------------------------------


def test_fps_below_threshold_but_within_window_does_not_fire(
    monitor: HealthMonitor, clock: _FakeClock
) -> None:
    events = monitor.record_heartbeat(Heartbeat(seq=1), metrics={"fps": 5.0})
    assert events == []
    clock.advance(3.0)  # still under fps_min_window_seconds (5 s)
    events = monitor.record_heartbeat(Heartbeat(seq=2), metrics={"fps": 5.0})
    assert events == []


def test_fps_below_threshold_for_full_window_fires_once(
    monitor: HealthMonitor, clock: _FakeClock
) -> None:
    monitor.record_heartbeat(Heartbeat(seq=1), metrics={"fps": 5.0})
    clock.advance(5.0)
    events = monitor.record_heartbeat(Heartbeat(seq=2), metrics={"fps": 5.0})
    assert [type(e).__name__ for e in events] == ["HealthDegraded"]
    assert isinstance(events[0], HealthDegraded)
    assert events[0].signal == "fps"  # type: ignore[attr-defined]
    # And does not re-fire on a subsequent heartbeat that's still bad.
    clock.advance(1.0)
    events = monitor.record_heartbeat(Heartbeat(seq=3), metrics={"fps": 5.0})
    assert events == []


def test_fps_recovery_clears_degraded(
    monitor: HealthMonitor, clock: _FakeClock
) -> None:
    # Drive it degraded first.
    monitor.record_heartbeat(Heartbeat(seq=1), metrics={"fps": 5.0})
    clock.advance(6.0)
    monitor.record_heartbeat(Heartbeat(seq=2), metrics={"fps": 5.0})
    # Now recover.
    clock.advance(1.0)
    events = monitor.record_heartbeat(Heartbeat(seq=3), metrics={"fps": 30.0})
    assert events == []
    # Going bad again must fire once.
    clock.advance(6.0)
    monitor.record_heartbeat(Heartbeat(seq=4), metrics={"fps": 4.0})
    clock.advance(6.0)
    events = monitor.record_heartbeat(Heartbeat(seq=5), metrics={"fps": 4.0})
    assert events and isinstance(events[0], HealthDegraded)


# ---------------------------------------------------------------------------
# Battery threshold
# ---------------------------------------------------------------------------


def test_low_battery_fires_once(monitor: HealthMonitor) -> None:
    events = monitor.record_heartbeat(Heartbeat(seq=1), metrics={"battery_percent": 5})
    assert [type(e).__name__ for e in events] == ["HealthDegraded"]
    # Same reading again must not re-fire.
    events = monitor.record_heartbeat(Heartbeat(seq=2), metrics={"battery_percent": 5})
    assert events == []


def test_battery_recovery_clears_state(monitor: HealthMonitor) -> None:
    monitor.record_heartbeat(Heartbeat(seq=1), metrics={"battery_percent": 5})
    # Recovery.
    monitor.record_heartbeat(Heartbeat(seq=2), metrics={"battery_percent": 80})
    # Drop again -> fresh event.
    events = monitor.record_heartbeat(Heartbeat(seq=3), metrics={"battery_percent": 5})
    assert len(events) == 1


# ---------------------------------------------------------------------------
# RSSI threshold
# ---------------------------------------------------------------------------


def test_weak_rssi_fires_once(monitor: HealthMonitor) -> None:
    events = monitor.record_heartbeat(Heartbeat(seq=1), metrics={"rssi_dbm": -90})
    assert len(events) == 1
    assert isinstance(events[0], HealthDegraded)
    assert events[0].signal == "rssi"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Thresholds override
# ---------------------------------------------------------------------------


def test_thresholds_are_configurable() -> None:
    # Very strict: fps_min=25, windowed at 0 s means instant fire.
    monitor = HealthMonitor(
        thresholds=HealthThresholds(fps_min=25.0, fps_min_window_seconds=0.0),
    )
    events = monitor.record_heartbeat(Heartbeat(seq=1), metrics={"fps": 20.0})
    assert len(events) == 1
    assert isinstance(events[0], HealthDegraded)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_reset_clears_all_state(monitor: HealthMonitor, clock: _FakeClock) -> None:
    monitor.record_heartbeat(Heartbeat(seq=1), metrics={"battery_percent": 5})
    monitor.reset()
    # After reset, same bad reading fires again.
    events = monitor.record_heartbeat(Heartbeat(seq=2), metrics={"battery_percent": 5})
    assert len(events) == 1
