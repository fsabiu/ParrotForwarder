from __future__ import annotations

import struct

import pytest

from parrot_forwarder.klv_encoder import MISB0601Encoder, encode_telemetry_to_klv


def _parse_lds(packet: bytes) -> dict[int, bytes]:
    assert packet.startswith(MISB0601Encoder.MISB_0601_KEY)
    offset = len(MISB0601Encoder.MISB_0601_KEY)
    length_byte = packet[offset]
    offset += 1
    if length_byte < 128:
        value_length = length_byte
    elif length_byte == 0x81:
        value_length = packet[offset]
        offset += 1
    elif length_byte == 0x82:
        value_length = struct.unpack(">H", packet[offset : offset + 2])[0]
        offset += 2
    else:  # pragma: no cover - current encoder won't hit this path
        raise AssertionError(f"unsupported BER length prefix {length_byte!r}")

    tags: dict[int, bytes] = {}
    end_offset = offset + value_length
    while offset < end_offset:
        tag = packet[offset]
        item_length = packet[offset + 1]
        offset += 2
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
