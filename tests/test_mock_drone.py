"""
Unit tests for :class:`parrot_forwarder.testing.MockDrone`.

The mock is pure-Python - these tests run on any host.

They cover:
  - default happy-drone behavior on connect/disconnect
  - get_state lookup by message class ``__name__``
  - every test-knob (battery, GPS, disconnect, raise_on_next_get_state,
    fail_next_connect, custom connect delay)
  - subscription factory shape
  - the ParrotForwarder ``drone_factory`` DI seam accepts MockDrone
"""

from __future__ import annotations

import inspect
import threading
import time
from types import SimpleNamespace

import pytest

from parrot_forwarder.testing import MockDrone, MockSubscription
from parrot_forwarder.testing.mock_drone import mock_drone_factory


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------


def test_defaults_to_disconnected_and_happy_state() -> None:
    drone = MockDrone("192.168.53.1")
    assert drone.is_connected is False
    # Happy defaults before any connect.
    drone.set_connect_delay(0)
    drone.connect()
    assert drone.is_connected is True
    battery = drone.get_state(SimpleNamespace(__name__="BatteryStateChanged"))
    assert battery == {"percent": 75}
    gps = drone.get_state(SimpleNamespace(__name__="GPSFixStateChanged"))
    assert gps == {"fixed": 1}


def test_connect_returns_true_and_respects_delay() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0.05)
    t0 = time.monotonic()
    assert drone.connect() is True
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.05, f"connect returned too fast: {elapsed:.3f}s"
    assert drone.is_connected


def test_disconnect_returns_true_and_clears_connected() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()
    assert drone.disconnect() is True
    assert drone.is_connected is False


def test_fail_next_connect_raises_once() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.fail_next_connect(ConnectionError("usb cable yanked"))
    with pytest.raises(ConnectionError, match="usb cable yanked"):
        drone.connect()
    # Next connect succeeds (one-shot).
    assert drone.connect() is True
    assert drone.is_connected


def test_force_disconnect_simulates_drop() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()
    drone.force_disconnect()
    assert drone.is_connected is False
    with pytest.raises(ConnectionError):
        drone.get_state(SimpleNamespace(__name__="BatteryStateChanged"))


# ---------------------------------------------------------------------------
# get_state
# ---------------------------------------------------------------------------


def test_get_state_uses_message_class_name() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()
    # Real Olympe passes a class - MockDrone looks up by __name__.
    assert drone.get_state(SimpleNamespace(__name__="BatteryStateChanged")) == {"percent": 75}
    # Unknown message names return None (mirrors Olympe behavior when
    # the drone hasn't produced that event yet).
    assert drone.get_state(SimpleNamespace(__name__="NopeNopeNope")) is None


def test_get_state_before_connect_raises() -> None:
    drone = MockDrone()
    with pytest.raises(ConnectionError, match="not connected"):
        drone.get_state(SimpleNamespace(__name__="BatteryStateChanged"))


def test_raise_on_next_get_state_is_one_shot() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()
    drone.raise_on_next_get_state(RuntimeError("olympe ate itself"))
    with pytest.raises(RuntimeError, match="olympe ate itself"):
        drone.get_state(SimpleNamespace(__name__="BatteryStateChanged"))
    # Subsequent calls succeed.
    assert drone.get_state(SimpleNamespace(__name__="BatteryStateChanged")) == {"percent": 75}


# ---------------------------------------------------------------------------
# State setters
# ---------------------------------------------------------------------------


def test_set_battery_percent_updates_state() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()
    drone.set_battery_percent(42)
    assert drone.get_state(SimpleNamespace(__name__="BatteryStateChanged")) == {"percent": 42}


def test_set_battery_percent_validates_range() -> None:
    drone = MockDrone()
    with pytest.raises(ValueError):
        drone.set_battery_percent(-1)
    with pytest.raises(ValueError):
        drone.set_battery_percent(101)


def test_set_gps_fix_encodes_as_olympe_integer() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()
    drone.set_gps_fix(False)
    assert drone.get_state(SimpleNamespace(__name__="GPSFixStateChanged")) == {"fixed": 0}
    drone.set_gps_fix(True)
    assert drone.get_state(SimpleNamespace(__name__="GPSFixStateChanged")) == {"fixed": 1}


def test_set_attitude_and_position_roundtrip() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()
    drone.set_attitude(roll=0.1, pitch=-0.2, yaw=1.5)
    drone.set_position(latitude=45.0, longitude=9.0, altitude=120.0)
    assert drone.get_state(SimpleNamespace(__name__="AttitudeChanged")) == {
        "roll": 0.1,
        "pitch": -0.2,
        "yaw": 1.5,
    }
    assert drone.get_state(SimpleNamespace(__name__="PositionChanged")) == {
        "latitude": 45.0,
        "longitude": 9.0,
        "altitude": 120.0,
    }


def test_set_state_escape_hatch() -> None:
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()
    drone.set_state("CustomMessage", {"foo": "bar"})
    assert drone.get_state(SimpleNamespace(__name__="CustomMessage")) == {"foo": "bar"}


# ---------------------------------------------------------------------------
# Subscription surface
# ---------------------------------------------------------------------------


def test_call_returns_mock_subscription_and_records_it() -> None:
    drone = MockDrone()
    sub = drone(SimpleNamespace(__name__="SomeEvent"))
    assert isinstance(sub, MockSubscription)
    assert sub.message_name == "SomeEvent"
    assert drone.subscriptions == [sub]


def test_mock_subscription_wait_and_unsubscribe() -> None:
    sub = MockSubscription(message_name="X")
    assert bool(sub) is True
    sub.wait(timeout=1.0)
    assert "wait(timeout=1.0)" in sub.calls
    sub.unsubscribe()
    assert bool(sub) is False
    assert sub.success() is False


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_mock_drone_is_thread_safe_against_state_mutation() -> None:
    """Stress-test: many threads hitting get_state while another thread
    mutates state. Must not raise, must not report stale garbage.
    """
    drone = MockDrone()
    drone.set_connect_delay(0)
    drone.connect()

    stop = threading.Event()
    errors: list[Exception] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                drone.get_state(SimpleNamespace(__name__="BatteryStateChanged"))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

    def writer() -> None:
        for pct in range(50):
            drone.set_battery_percent(pct % 100)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    w = threading.Thread(target=writer)
    for t in threads:
        t.start()
    w.start()
    w.join()
    stop.set()
    for t in threads:
        t.join(timeout=1)
    assert errors == []


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def test_mock_drone_factory_applies_defaults() -> None:
    factory = mock_drone_factory(connect_delay=0, battery_percent=30, gps_fix=False)
    drone = factory("10.0.0.1")
    assert isinstance(drone, MockDrone)
    assert drone.ip == "10.0.0.1"
    drone.connect()
    assert drone.get_state(SimpleNamespace(__name__="BatteryStateChanged")) == {"percent": 30}
    assert drone.get_state(SimpleNamespace(__name__="GPSFixStateChanged")) == {"fixed": 0}


# ---------------------------------------------------------------------------
# DI seam on ParrotForwarder
# ---------------------------------------------------------------------------


def test_parrot_forwarder_accepts_drone_factory_param() -> None:
    """T03 acceptance: ParrotForwarder must expose a ``drone_factory``
    parameter so tests can inject MockDrone without Olympe installed.
    We inspect the signature rather than instantiate, because
    ParrotForwarder's telemetry/video submodules still import Olympe
    eagerly (they're touched in later tasks).
    """
    # Importing main must not require Olympe (top-level import removed in T03).
    from parrot_forwarder import main  # noqa: F401

    # Use getattr to avoid the lazy re-export in __init__.
    params = inspect.signature(main.ParrotForwarder.__init__).parameters
    assert "drone_factory" in params, (
        "ParrotForwarder.__init__ must accept a drone_factory for DI"
    )
    # Default must be None (the module picks up the real Olympe factory lazily).
    assert params["drone_factory"].default is None
    # Install_signal_handlers escape hatch present (tests may need it).
    assert "install_signal_handlers" in params
