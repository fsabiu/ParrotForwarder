from __future__ import annotations

from parrot_forwarder.klv_encoder import (
    AION_TELEMETRY_CONTRACT_VERSION,
    MISB0601Encoder,
    encode_telemetry_to_klv,
)
from parrot_forwarder.tools.recording_audit import audit_klv_bytes


def test_audit_klv_bytes_reports_tag120_cadence_and_fields() -> None:
    packets: list[bytes] = []
    for seq in range(3):
        packet = encode_telemetry_to_klv(
            {
                "timestamp": f"2026-05-15T12:00:00.0{seq}0Z",
                "timestamp_us": 1_700_000_000_000_000 + (seq * 33_333),
                "sequence": seq,
                "position_valid": False,
                "position_is_default": False,
                "position_latitude": None,
                "position_longitude": None,
                "latitude": None,
                "longitude": None,
                "altitude": None,
                "source_id": "anafi",
                "source_name": "Anafi",
                "battery_percent": 73,
                "altitude_agl": 1.5,
                "altitude_relative_takeoff_m": 1.7,
                "product_name": "Anafi",
                "olympe_state_count": 1,
            }
        )
        assert packet is not None
        packets.append(packet)

    report = audit_klv_bytes(b"".join(packets))

    assert report["packets"] == 3
    assert report["tags"]["120"] == 3
    tag120 = report["tag120"]
    assert tag120["count"] == 3
    assert tag120["contract_versions"] == {AION_TELEMETRY_CONTRACT_VERSION: 3}
    assert tag120["source_ids"] == {"anafi": 3}
    assert tag120["gps"]["invalid_samples"] == 3
    assert tag120["gps"]["default_coordinate_samples"] == 0
    assert tag120["altitude"]["agl_m"]["mean"] == 1.5


def test_audit_klv_bytes_reports_legacy_file_without_tag120() -> None:
    encoder = MISB0601Encoder()
    encoder.add_timestamp(1_700_000_000_000_000)
    encoder.add_latitude(36.7)
    encoder.add_longitude(-4.28)
    encoder.add_altitude(100.0)

    report = audit_klv_bytes(encoder.pack())

    assert report["tag120"]["count"] == 0
    assert report["tag120"]["missing_fields"]
