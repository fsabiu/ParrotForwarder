"""Audit ParrotForwarder MPEG-TS recordings for video and KLV telemetry."""

from __future__ import annotations

import argparse
import json
import statistics
import struct
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parrot_forwarder.klv_encoder import MISB0601Encoder
from parrot_forwarder.tools.klv_tag120 import (
    KlvParseError,
    iter_local_set_items,
    iter_misb0601_packets,
)

GAP_THRESHOLD_S = 0.050
REQUIRED_TAG120_FIELDS = (
    "source_id",
    "source_name",
    "battery_percent",
    "rssi_dbm",
    "gps_fix",
    "position_valid",
    "position_latitude",
    "position_longitude",
    "position_altitude_msl",
    "altitude_agl",
    "altitude_relative_takeoff_m",
    "heading_deg",
    "gimbal_pitch_abs",
    "gimbal_pitch_rel",
    "camera_zoom_level",
    "camera_h_fov_deg",
    "camera_v_fov_deg",
    "product_name",
    "olympe_state_count",
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _jsonable_float(value: object) -> float | None:
    if value in (None, "N/A"):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame_time(frame: dict[str, Any]) -> float | None:
    value = _jsonable_float(frame.get("best_effort_timestamp_time"))
    if value is not None:
        return value
    return _jsonable_float(frame.get("pkt_pts_time"))


def _run_json(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    decoded = json.loads(proc.stdout or "{}")
    if not isinstance(decoded, dict):
        raise RuntimeError(f"expected JSON object from {' '.join(cmd)}")
    return decoded


def _run_bytes(cmd: list[str]) -> bytes:
    proc = subprocess.run(cmd, check=True, capture_output=True)
    return proc.stdout


def _series_stats(times: list[float]) -> dict[str, object]:
    if not times:
        return {
            "count": 0,
            "duration_s": None,
            "average_hz": None,
            "max_gap_s": None,
            "gaps_over_50ms": 0,
            "monotonic": True,
        }
    ordered = times
    gaps = [b - a for a, b in zip(ordered, ordered[1:], strict=False)]
    duration = ordered[-1] - ordered[0] if len(ordered) > 1 else 0.0
    return {
        "count": len(ordered),
        "duration_s": duration,
        "average_hz": (len(ordered) - 1) / duration if duration > 0 else None,
        "max_gap_s": max(gaps) if gaps else None,
        "gaps_over_50ms": sum(1 for gap in gaps if gap > GAP_THRESHOLD_S),
        "monotonic": all(gap >= 0 for gap in gaps),
    }


def _number_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
    }


def _packet_timestamp_us(items: list[tuple[int, bytes]]) -> int | None:
    for tag, value in items:
        if tag == MISB0601Encoder.TAG_UNIX_TIMESTAMP and len(value) == 8:
            return int(struct.unpack(">Q", value)[0])
    return None


def _decode_tag120(value: bytes) -> dict[str, Any] | None:
    decoded = json.loads(value.decode("utf-8"))
    return decoded if isinstance(decoded, dict) else None


def audit_klv_bytes(data: bytes) -> dict[str, object]:
    packets = iter_misb0601_packets(data)
    tag_counts: Counter[int] = Counter()
    packet_timestamps_s: list[float] = []
    tag120_payloads: list[dict[str, Any]] = []
    parse_errors = 0

    for packet in packets:
        try:
            items = iter_local_set_items(packet)
        except KlvParseError:
            parse_errors += 1
            continue
        tag_counts.update(tag for tag, _value in items)
        timestamp_us = _packet_timestamp_us(items)
        if timestamp_us is not None:
            packet_timestamps_s.append(timestamp_us / 1_000_000.0)
        for tag, value in items:
            if tag != MISB0601Encoder.TAG_AION_TELEMETRY_JSON:
                continue
            try:
                payload = _decode_tag120(value)
            except (UnicodeDecodeError, json.JSONDecodeError):
                parse_errors += 1
                continue
            if payload is not None:
                tag120_payloads.append(payload)

    return {
        "packets": len(packets),
        "parse_errors": parse_errors,
        "tags": {str(tag): count for tag, count in sorted(tag_counts.items())},
        "cadence": _series_stats(packet_timestamps_s),
        "tag120": audit_tag120_payloads(tag120_payloads),
    }


def audit_tag120_payloads(payloads: list[dict[str, Any]]) -> dict[str, object]:
    tag120_times_s: list[float] = []
    field_counts: Counter[str] = Counter()
    source_ids: Counter[str] = Counter()
    source_names: Counter[str] = Counter()
    contract_versions: Counter[str] = Counter()
    gps_valid = 0
    gps_invalid = 0
    null_coordinate_samples = 0
    default_coordinate_samples = 0
    altitude_agl_values: list[float] = []
    altitude_relative_values: list[float] = []
    altitude_msl_values: list[float] = []

    for payload in payloads:
        timestamp_us = payload.get("timestamp_us")
        telemetry = payload.get("telemetry")
        if not isinstance(telemetry, dict):
            telemetry = {}
        if isinstance(timestamp_us, int | float):
            tag120_times_s.append(float(timestamp_us) / 1_000_000.0)
        elif isinstance(telemetry.get("timestamp_us"), int | float):
            tag120_times_s.append(float(telemetry["timestamp_us"]) / 1_000_000.0)

        contract_version = payload.get("contract_version")
        if isinstance(contract_version, str):
            contract_versions[contract_version] += 1

        source_id = payload.get("source_id") or telemetry.get("source_id")
        source_name = payload.get("source_name") or telemetry.get("source_name")
        if isinstance(source_id, str) and source_id:
            source_ids[source_id] += 1
        if isinstance(source_name, str) and source_name:
            source_names[source_name] += 1

        for field in REQUIRED_TAG120_FIELDS:
            if telemetry.get(field) is not None or payload.get(field) is not None:
                field_counts[field] += 1

        if telemetry.get("position_valid") is True:
            gps_valid += 1
        else:
            gps_invalid += 1
        if telemetry.get("position_is_default") is True:
            default_coordinate_samples += 1
        if telemetry.get("position_latitude") is None or telemetry.get("position_longitude") is None:
            null_coordinate_samples += 1

        for key, target in (
            ("altitude_agl", altitude_agl_values),
            ("altitude_relative_takeoff_m", altitude_relative_values),
            ("position_altitude_msl", altitude_msl_values),
        ):
            value = telemetry.get(key)
            if isinstance(value, int | float):
                target.append(float(value))

    missing_fields = [
        field for field in REQUIRED_TAG120_FIELDS if field_counts.get(field, 0) == 0
    ]
    return {
        "count": len(payloads),
        "cadence": _series_stats(tag120_times_s),
        "contract_versions": dict(contract_versions),
        "source_ids": dict(source_ids),
        "source_names": dict(source_names),
        "field_counts": {field: field_counts.get(field, 0) for field in REQUIRED_TAG120_FIELDS},
        "missing_fields": missing_fields,
        "gps": {
            "valid_samples": gps_valid,
            "invalid_samples": gps_invalid,
            "null_coordinate_samples": null_coordinate_samples,
            "default_coordinate_samples": default_coordinate_samples,
        },
        "altitude": {
            "agl_m": _number_stats(altitude_agl_values),
            "relative_takeoff_m": _number_stats(altitude_relative_values),
            "msl_m": _number_stats(altitude_msl_values),
        },
    }


def audit_video(path: Path) -> dict[str, object]:
    info = _run_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    raw_streams = info.get("streams")
    streams: list[Any] = raw_streams if isinstance(raw_streams, list) else []
    video_stream: dict[str, Any] = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        {},
    )
    duration = _jsonable_float(video_stream.get("duration"))
    if duration is None:
        raw_format = info.get("format")
        duration = _jsonable_float(
            raw_format.get("duration") if isinstance(raw_format, dict) else None
        )

    frames = _run_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time,pkt_pts_time",
            "-of",
            "json",
            str(path),
        ]
    )
    raw_frame_items = frames.get("frames")
    frame_items: list[Any] = raw_frame_items if isinstance(raw_frame_items, list) else []
    frame_times: list[float] = []
    for frame in frame_items:
        if not isinstance(frame, dict):
            continue
        time_value = _frame_time(frame)
        if time_value is not None:
            frame_times.append(time_value)

    return {
        "codec": video_stream.get("codec_name"),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "avg_frame_rate": video_stream.get("avg_frame_rate"),
        "duration_s": duration,
        "frames": _series_stats(frame_times),
    }


def audit_recording(path: Path) -> dict[str, object]:
    klv_bytes = _run_bytes(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:d:0",
            "-c",
            "copy",
            "-f",
            "data",
            "-",
        ]
    )
    return {
        "file": str(path),
        "generated_at": _utc_now_iso(),
        "video": audit_video(path),
        "klv": audit_klv_bytes(klv_bytes),
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="parrot-forwarder-recording-audit",
        description="Audit a ParrotForwarder MPEG-TS file for video and KLV tag 120 telemetry.",
    )
    parser.add_argument("recording", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    path = args.recording
    if not path.exists():
        print(f"recording not found: {path}", file=sys.stderr)
        return 2
    try:
        report = audit_recording(path)
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError, KlvParseError) as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 1
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
