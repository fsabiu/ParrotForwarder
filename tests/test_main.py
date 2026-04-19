from __future__ import annotations

import sys
import types

from parrot_forwarder.main import ParrotForwarder


class _ConnectionStateDrone:
    def __init__(self) -> None:
        self._connected = True

    def connection_state(self) -> bool:
        return False

    def get_state(self, _message) -> dict[str, object]:
        return {"percent": 75}


class _LegacyDrone:
    _connected = True

    def get_state(self, _message) -> dict[str, object]:
        return {"percent": 75}


class _DroneManagerStateDrone:
    def __init__(self, state: str) -> None:
        self._state = state

    def connection_state(self) -> bool:
        return True

    def get_state(self, message) -> dict[str, object]:
        module = getattr(message, "__module__", "")
        name = getattr(message, "__name__", "")
        if "drone_manager" in module or name == "connection_state":
            return {"state": self._state}
        return {"percent": 75}


def _forwarder_for_test() -> ParrotForwarder:
    return ParrotForwarder(
        drone_ip="192.168.53.1",
        drone_factory=lambda _ip: object(),
        install_signal_handlers=False,
    )


def test_is_drone_connected_prefers_connection_state_over_cached_state() -> None:
    forwarder = _forwarder_for_test()
    forwarder.drone = _ConnectionStateDrone()

    assert forwarder.is_drone_connected() is False


def test_is_drone_connected_falls_back_to_state_probe_without_connection_state() -> None:
    forwarder = _forwarder_for_test()
    forwarder.drone = _LegacyDrone()

    assert forwarder.is_drone_connected() is True


def test_is_drone_connected_uses_drone_manager_state_when_available(monkeypatch) -> None:
    fake_module = types.ModuleType("olympe.messages.drone_manager")

    def connection_state():  # type: ignore[no-redef]
        return None

    fake_module.connection_state = connection_state
    monkeypatch.setitem(sys.modules, "olympe.messages.drone_manager", fake_module)

    forwarder = _forwarder_for_test()
    forwarder.drone = _DroneManagerStateDrone("disconnected")

    assert forwarder.is_drone_connected() is False
