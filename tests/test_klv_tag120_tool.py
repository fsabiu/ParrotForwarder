from __future__ import annotations

import pytest

from parrot_forwarder.klv_encoder import (
    AION_TELEMETRY_CONTRACT_VERSION,
    encode_telemetry_to_klv,
)
from parrot_forwarder.tools.klv_tag120 import (
    KlvParseError,
    extract_all_tag120_json,
    extract_tag120_json,
)


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


def test_extract_tag120_json_from_ffmpeg_stripped_klv_packet() -> None:
    packet = encode_telemetry_to_klv(
        {
            "timestamp": "2026-05-15T08:00:00.000Z",
            "timestamp_us": 1_768_464_000_000_000,
            "sequence": 8,
            "position_valid": False,
        }
    )

    assert packet is not None
    payload = extract_tag120_json(packet[10:])

    assert payload is not None
    assert payload["contract_version"] == AION_TELEMETRY_CONTRACT_VERSION
    assert payload["sequence"] == 8


def test_extract_tag120_json_returns_none_without_misb_key() -> None:
    assert extract_tag120_json(b"not klv") is None


def test_extract_all_tag120_json_returns_multiple_payloads() -> None:
    first = encode_telemetry_to_klv(
        {"timestamp_us": 1, "sequence": 1, "position_valid": False}
    )
    second = encode_telemetry_to_klv(
        {"timestamp_us": 2, "sequence": 2, "position_valid": False}
    )

    assert first is not None
    assert second is not None
    payloads = extract_all_tag120_json(first + b"noise" + second)

    assert [payload["sequence"] for payload in payloads] == [1, 2]


def test_extract_all_tag120_json_returns_multiple_ffmpeg_stripped_payloads() -> None:
    first = encode_telemetry_to_klv(
        {"timestamp_us": 1, "sequence": 1, "position_valid": False}
    )
    second = encode_telemetry_to_klv(
        {"timestamp_us": 2, "sequence": 2, "position_valid": False}
    )

    assert first is not None
    assert second is not None
    payloads = extract_all_tag120_json(first[10:] + second[10:])

    assert [payload["sequence"] for payload in payloads] == [1, 2]


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
