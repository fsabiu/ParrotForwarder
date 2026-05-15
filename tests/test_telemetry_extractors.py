from __future__ import annotations

from parrot_forwarder.telemetry_extractors import sdk_wifi_rssi_dbm


def test_sdk_wifi_rssi_dbm_extracts_raw_olympe_wifi_rssi() -> None:
    assert sdk_wifi_rssi_dbm({"wifi.rssi_changed": {"rssi": -43}}) == -43.0


def test_sdk_wifi_rssi_dbm_rejects_missing_or_invalid_values() -> None:
    assert sdk_wifi_rssi_dbm({}) is None
    assert sdk_wifi_rssi_dbm({"wifi.rssi_changed": {"rssi": True}}) is None
    assert sdk_wifi_rssi_dbm({"wifi.rssi_changed": {"rssi": "bad"}}) is None
