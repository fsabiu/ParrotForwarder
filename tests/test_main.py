from __future__ import annotations

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
