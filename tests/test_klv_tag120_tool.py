from __future__ import annotations

import pytest

from parrot_forwarder.klv_encoder import (
    AION_TELEMETRY_CONTRACT_VERSION,
    encode_telemetry_to_klv,
)
from parrot_forwarder.tools.klv_tag120 import KlvParseError, extract_tag120_json


def test_extract_tag120_json_from_klv_packet() -> None:
    packet = encode_telemetry_to_klv(
        {
            "timestamp": "2026-05-15T08:00:00.000Z",
            "timestamp_us": 1_768_464_000_000_000,
            "sequence": 7,
            "latitude": 36.7,
            "longitude": -4.28,
            "altitude": 100.0,
            "telemetry_target_hz": 30,
        }
    )

    assert packet is not None
    payload = extract_tag120_json(b"noise" + packet)

    assert payload is not None
    assert payload["contract_version"] == AION_TELEMETRY_CONTRACT_VERSION
    assert payload["source"] == "parrot_forwarder"
    assert payload["sequence"] == 7
    assert payload["telemetry"]["telemetry_target_hz"] == 30


def test_extract_tag120_json_returns_none_without_misb_key() -> None:
    assert extract_tag120_json(b"not klv") is None


def test_extract_tag120_json_rejects_truncated_packet() -> None:
    packet = encode_telemetry_to_klv(
        {
            "timestamp_us": 1_768_464_000_000_000,
            "latitude": 36.7,
            "longitude": -4.28,
            "altitude": 100.0,
        }
    )

    assert packet is not None
    with pytest.raises(KlvParseError):
        extract_tag120_json(packet[:-4])
