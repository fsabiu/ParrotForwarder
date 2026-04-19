"""
MockDrone - Olympe stand-in for unit and integration tests.

Covers only the subset of ``olympe.Drone`` actually called by the v1
codebase: ``connect``, ``disconnect``, ``get_state``, and the callable
subscription surface (``drone(MessageClass)``).

Tests configure behavior with explicit setters (``set_battery_percent``,
``set_gps_fix``, ``force_disconnect``, ``raise_on_next_get_state``,
``fail_next_connect``) rather than by patching attributes. Defaults are
deliberately "happy drone": :meth:`connect` returns ``True`` after a
short simulated delay, battery reports 75 percent, GPS fix is true, and
attitude is level.

Not supported:
- Actual RTSP frames. Use the GStreamer mock in T11 for that.
- Enforcing the precise async semantics of real Olympe subscriptions.
  Subscriptions here are synchronous stubs that record callers.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default state
# ---------------------------------------------------------------------------


def _default_state() -> dict[str, dict[str, Any]]:
    """The "happy drone" state used until a test sets otherwise.

    Keys are message-class names (``MessageClass.__name__``). Values are
    the dict-like payloads Olympe returns from ``get_state``.
    """
    return {
        "BatteryStateChanged": {"percent": 75},
        "GPSFixStateChanged": {"fixed": 1},
        "AttitudeChanged": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
        "AltitudeChanged": {"altitude": 0.0},
        "PositionChanged": {"latitude": 0.0, "longitude": 0.0, "altitude": 0.0},
        "SpeedChanged": {"speedX": 0.0, "speedY": 0.0, "speedZ": 0.0},
        "FlyingStateChanged": {"state": "landed"},
        "attitude": {"yaw_absolute": 0.0, "pitch_absolute": 0.0, "roll_absolute": 0.0,
                     "yaw_relative": 0.0, "pitch_relative": 0.0, "roll_relative": 0.0},
        "offsets": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "alignment_offsets": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
    }


# ---------------------------------------------------------------------------
# Subscription stub
# ---------------------------------------------------------------------------


@dataclass
class MockSubscription:
    """Returned from ``MockDrone(SomeMessage)`` - Olympe's subscription handle.

    The real Olympe subscription has ``.wait()``, ``.unsubscribe()``, and
    a truthy bool check. We provide enough of that surface for tests to
    exercise code paths that call these methods without actually blocking.
    """

    message_name: str
    _timeout: float | None = None
    _unsubscribed: bool = False
    calls: list[str] = field(default_factory=list)

    def wait(self, timeout: float | None = None) -> MockSubscription:
        self.calls.append(f"wait(timeout={timeout})")
        self._timeout = timeout
        return self

    def unsubscribe(self) -> None:
        self.calls.append("unsubscribe()")
        self._unsubscribed = True

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return not self._unsubscribed

    # Real Olympe uses ``.success()`` on some expectations. Provide it so
    # callers don't crash; it mirrors the subscription being still live.
    def success(self) -> bool:
        return not self._unsubscribed


# ---------------------------------------------------------------------------
# MockDrone
# ---------------------------------------------------------------------------


class MockDrone:
    """A minimal stand-in for :class:`olympe.Drone`.

    Constructor signature matches Olympe: ``MockDrone(ip)``. Internal
    threading lock keeps control-setter methods safe against the thread
    running the forwarder under test.
    """

    def __init__(self, ip: str = "192.168.53.1") -> None:
        self.ip = ip
        self._connected: bool = False
        self._lock = threading.RLock()

        # Configurable behavior (test knobs).
        self._connect_delay_seconds: float = 0.1
        self._fail_next_connect: Exception | None = None
        self._raise_on_next_get_state: Exception | None = None
        self._state: dict[str, dict[str, Any]] = _default_state()

        # Subscription bookkeeping so tests can assert "this was subscribed".
        self.subscriptions: list[MockSubscription] = []

    # ------------------------------------------------------------------
    # Olympe-shaped surface used by production code
    # ------------------------------------------------------------------

    def connect(self, *args: Any, **kwargs: Any) -> bool:
        """Simulate Olympe's blocking connect. Returns True on success."""
        with self._lock:
            if self._fail_next_connect is not None:
                exc = self._fail_next_connect
                self._fail_next_connect = None
                raise exc
            delay = self._connect_delay_seconds
        # Sleep OUTSIDE the lock so tests can mutate state concurrently.
        if delay > 0:
            time.sleep(delay)
        with self._lock:
            self._connected = True
        logger.debug("MockDrone(%s) connected", self.ip)
        return True

    def disconnect(self, *args: Any, **kwargs: Any) -> bool:
        """Simulate Olympe's blocking disconnect."""
        with self._lock:
            self._connected = False
        logger.debug("MockDrone(%s) disconnected", self.ip)
        return True

    def connection_state(self) -> bool:
        """Mirror Olympe's connection-state helper."""
        with self._lock:
            return self._connected

    def get_state(self, message_class: Any) -> dict[str, Any] | None:
        """Mirror ``olympe.Drone.get_state(MessageClass)``.

        Looks up state by ``message_class.__name__`` so tests can pass
        either a real Olympe message class or any sentinel with the
        matching ``__name__`` attribute.
        """
        with self._lock:
            if not self._connected:
                raise ConnectionError("MockDrone is not connected")
            if self._raise_on_next_get_state is not None:
                exc = self._raise_on_next_get_state
                self._raise_on_next_get_state = None
                raise exc
            name = getattr(message_class, "__name__", str(message_class))
            return self._state.get(name)

    def __call__(self, message_class: Any) -> MockSubscription:
        """Mirror Olympe's ``drone(MessageClass)`` subscription factory."""
        name = getattr(message_class, "__name__", str(message_class))
        sub = MockSubscription(message_name=name)
        with self._lock:
            self.subscriptions.append(sub)
        return sub

    # ------------------------------------------------------------------
    # Test knobs
    # ------------------------------------------------------------------

    def set_connect_delay(self, seconds: float) -> None:
        """Override the simulated connect latency (default 100 ms)."""
        with self._lock:
            self._connect_delay_seconds = float(seconds)

    def fail_next_connect(self, exc: Exception | None = None) -> None:
        """Arm the next :meth:`connect` to raise ``exc`` (default ConnectionError)."""
        with self._lock:
            self._fail_next_connect = exc or ConnectionError("simulated connect failure")

    def force_disconnect(self) -> None:
        """Simulate the drone dropping connection without being asked."""
        with self._lock:
            self._connected = False

    def raise_on_next_get_state(self, exc: Exception | None = None) -> None:
        """Arm the next :meth:`get_state` call to raise ``exc`` once."""
        with self._lock:
            self._raise_on_next_get_state = exc or RuntimeError(
                "simulated olympe get_state failure"
            )

    def set_battery_percent(self, percent: int) -> None:
        if not 0 <= percent <= 100:
            raise ValueError(f"battery percent must be in [0, 100], got {percent}")
        self._set("BatteryStateChanged", {"percent": percent})

    def set_gps_fix(self, fixed: bool) -> None:
        self._set("GPSFixStateChanged", {"fixed": 1 if fixed else 0})

    def set_attitude(self, roll: float, pitch: float, yaw: float) -> None:
        self._set("AttitudeChanged", {"roll": roll, "pitch": pitch, "yaw": yaw})

    def set_position(self, latitude: float, longitude: float, altitude: float) -> None:
        self._set(
            "PositionChanged",
            {"latitude": latitude, "longitude": longitude, "altitude": altitude},
        )

    def set_state(self, message_name: str, value: dict[str, Any]) -> None:
        """Escape hatch for setting arbitrary Olympe state by class name."""
        self._set(message_name, value)

    def _set(self, name: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._state[name] = dict(value)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def mock_drone_factory(**defaults: Any) -> Callable[[str], MockDrone]:
    """Build a ``drone_factory`` (taking ``ip``) preconfigured with defaults.

    Example::

        forwarder = ParrotForwarder(
            drone_ip="192.0.2.1",
            drone_factory=mock_drone_factory(connect_delay=0.0),
        )
    """

    def _factory(ip: str) -> MockDrone:
        drone = MockDrone(ip)
        if "connect_delay" in defaults:
            drone.set_connect_delay(float(defaults["connect_delay"]))
        if "battery_percent" in defaults:
            drone.set_battery_percent(int(defaults["battery_percent"]))
        if "gps_fix" in defaults:
            drone.set_gps_fix(bool(defaults["gps_fix"]))
        return drone

    return _factory
