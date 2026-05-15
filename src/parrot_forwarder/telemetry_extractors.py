"""Small telemetry extraction helpers shared by runtime and tests."""

from __future__ import annotations

import math
from collections.abc import Mapping


def finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value_f = float(value)
        if math.isfinite(value_f):
            return value_f
    return None


def sdk_wifi_rssi_dbm(sdk_state: object) -> float | None:
    if not isinstance(sdk_state, Mapping):
        return None
    wifi_rssi = sdk_state.get("wifi.rssi_changed")
    if not isinstance(wifi_rssi, Mapping):
        return None
    return finite_number(wifi_rssi.get("rssi"))
