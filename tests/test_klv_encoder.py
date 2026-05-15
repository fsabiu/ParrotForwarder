from __future__ import annotations

import json
import struct

import pytest

from parrot_forwarder.klv_encoder import (
    AION_TELEMETRY_CONTRACT_VERSION,
    MISB0601Encoder,
    encode_telemetry_to_klv,
)


def _parse_ber_length(packet: bytes, offset: int) -> tuple[int, int]:
    length_byte = packet[offset]
    offset += 1
    if length_byte < 128:
        return length_byte, offset
    if length_byte == 0x81:
        return packet[offset], offset + 1
    if length_byte == 0x82:
        return struct.unpack(">H", packet[offset : offset + 2])[0], offset + 2
    raise AssertionError(f"unsupported BER length prefix {length_byte!r}")


def _parse_lds(packet: bytes) -> dict[int, bytes]:
    assert packet.startswith(MISB0601Encoder.MISB_0601_KEY)
    offset = len(MISB0601Encoder.MISB_0601_KEY)
    value_length, offset = _parse_ber_length(packet, offset)

    tags: dict[int, bytes] = {}
    end_offset = offset + value_length
    while offset < end_offset:
        tag = packet[offset]
        offset += 1
        item_length, offset = _parse_ber_length(packet, offset)
        tags[tag] = packet[offset : offset + item_length]
        offset += item_length
    return tags


def test_encode_telemetry_to_klv_uses_sensor_fov_tags_16_and_17() -> None:
    packet = encode_telemetry_to_klv(
        {
            "timestamp_us": 1_700_000_000_000_000,
            "latitude": 36.7,
            "longitude": -4.28,
            "altitude": 100.0,
            "sensor_h_fov": 76.6,
            "sensor_v_fov": 59.3,
        }
    )

    assert packet is not None
    tags = _parse_lds(packet)
    assert 16 in tags
    assert 17 in tags
    assert struct.unpack(">H", tags[16])[0] / 100.0 == pytest.approx(76.6, abs=0.01)
    assert struct.unpack(">H", tags[17])[0] / 100.0 == pytest.approx(59.3, abs=0.01)


def test_encode_telemetry_to_klv_adds_full_aion_json_extension() -> None:
    packet = encode_telemetry_to_klv(
        {
            "timestamp": "2026-05-12T12:00:00.000Z",
            "timestamp_us": 1_700_000_000_000_000,
            "sequence": 42,
            "latitude": 36.7,
            "longitude": -4.28,
            "altitude": 100.0,
            "battery_percent": 73,
            "position_valid": True,
            "gimbal_pitch_rel": -45.0,
            "camera_zoom_level": 1.2,
            "storage_free_space_mb": 1024,
        }
    )

    assert packet is not None
    tags = _parse_lds(packet)
    assert MISB0601Encoder.TAG_AION_TELEMETRY_JSON in tags
    payload = json.loads(tags[MISB0601Encoder.TAG_AION_TELEMETRY_JSON].decode("utf-8"))
    assert payload["contract_version"] == AION_TELEMETRY_CONTRACT_VERSION
    assert payload["source"] == "parrot_forwarder"
    assert payload["source_id"] == "parrot_anafi_unknown"
    assert payload["source_name"] == "parrot_anafi_unknown"
    assert payload["sequence"] == 42
    assert payload["telemetry"]["battery_percent"] == 73
    assert payload["telemetry"]["gimbal_pitch_rel"] == -45.0


def test_encode_telemetry_to_klv_preserves_raw_sdk_state_extension() -> None:
    packet = encode_telemetry_to_klv(
        {
            "timestamp": "2026-05-12T12:00:00.000Z",
            "timestamp_us": 1_700_000_000_000_000,
            "sequence": 43,
            "latitude": 36.7,
            "longitude": -4.28,
            "altitude": 100.0,
            "olympe_state_count": 1,
            "olympe_state": {
                "ardrone3.PilotingState.SpeedChanged": {
                    "speedX": 1.0,
                    "speedY": 2.0,
                    "speedZ": -0.5,
                }
            },
            "olympe_event_state": {
                "gimbal_attitude": {
                    "updated_at": "2026-05-12T12:00:00.000Z",
                    "payload": {"pitch_absolute": -35.0},
                }
            },
        }
    )

    assert packet is not None
    tags = _parse_lds(packet)
    payload = json.loads(tags[MISB0601Encoder.TAG_AION_TELEMETRY_JSON].decode("utf-8"))
    telemetry = payload["telemetry"]
    assert telemetry["olympe_state_count"] == 1
    assert telemetry["olympe_state"]["ardrone3.PilotingState.SpeedChanged"]["speedX"] == 1.0
    assert telemetry["olympe_event_state"]["gimbal_attitude"]["payload"]["pitch_absolute"] == -35.0


def test_encode_telemetry_to_klv_omits_geolocation_tags_when_position_invalid() -> None:
    packet = encode_telemetry_to_klv(
        {
            "timestamp": "2026-05-15T12:00:00.000Z",
            "timestamp_us": 1_700_000_000_000_000,
            "sequence": 44,
            "position_valid": False,
            "position_latitude": None,
            "position_longitude": None,
            "latitude": None,
            "longitude": None,
            "altitude": None,
            "source_name": "Anafi Living Room",
            "source_id": "anafi_living_room",
        }
    )

    assert packet is not None
    tags = _parse_lds(packet)
    assert 13 not in tags
    assert 14 not in tags
    assert 15 not in tags
    payload = json.loads(tags[MISB0601Encoder.TAG_AION_TELEMETRY_JSON].decode("utf-8"))
    assert payload["source_id"] == "anafi_living_room"
    assert payload["source_name"] == "Anafi Living Room"
    assert payload["telemetry"]["position_valid"] is False
