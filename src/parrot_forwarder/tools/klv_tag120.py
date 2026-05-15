"""Extract AION tag 120 JSON from MISB 0601 KLV bytes."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from parrot_forwarder.klv_encoder import MISB0601Encoder


class KlvParseError(ValueError):
    """Raised when a KLV packet is present but malformed."""


def parse_ber_length(data: bytes, offset: int) -> tuple[int, int]:
    """Parse one BER length field and return ``(length, next_offset)``."""
    if offset >= len(data):
        raise KlvParseError("missing BER length")
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    length_octets = first & 0x7F
    if length_octets == 0:
        raise KlvParseError("indefinite BER length is not supported")
    if length_octets > 4:
        raise KlvParseError(f"unsupported BER length width: {length_octets}")
    end = offset + length_octets
    if end > len(data):
        raise KlvParseError("truncated BER length")
    return int.from_bytes(data[offset:end], byteorder="big"), end


def iter_local_set_items(packet: bytes) -> list[tuple[int, bytes]]:
    if not packet.startswith(MISB0601Encoder.MISB_0601_KEY):
        raise KlvParseError("packet does not start with MISB 0601 universal key")

    offset = len(MISB0601Encoder.MISB_0601_KEY)
    value_length, offset = parse_ber_length(packet, offset)
    end = offset + value_length
    if end > len(packet):
        raise KlvParseError("truncated MISB 0601 local set")

    items: list[tuple[int, bytes]] = []
    while offset < end:
        tag = packet[offset]
        offset += 1
        item_length, offset = parse_ber_length(packet, offset)
        item_end = offset + item_length
        if item_end > end:
            raise KlvParseError(f"tag {tag} extends beyond local set")
        items.append((tag, packet[offset:item_end]))
        offset = item_end
    return items


def iter_misb0601_packets(data: bytes) -> list[bytes]:
    """Return every complete MISB 0601 packet found in ``data``."""
    packets: list[bytes] = []
    key = MISB0601Encoder.MISB_0601_KEY
    start = data.find(key)
    while start != -1:
        try:
            offset = start + len(key)
            value_length, value_offset = parse_ber_length(data, offset)
            end = value_offset + value_length
            if end > len(data):
                raise KlvParseError("truncated MISB 0601 local set")
            packets.append(data[start:end])
            start = data.find(key, end)
        except KlvParseError:
            start = data.find(key, start + 1)
    return packets


def extract_all_tag120_json(data: bytes) -> list[dict[str, Any]]:
    """Return all decoded tag 120 JSON payloads found in ``data``."""
    payloads: list[dict[str, Any]] = []
    for packet in iter_misb0601_packets(data):
        for tag, value in iter_local_set_items(packet):
            if tag == MISB0601Encoder.TAG_AION_TELEMETRY_JSON:
                decoded = json.loads(value.decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise KlvParseError("tag 120 JSON payload is not an object")
                payloads.append(decoded)
    return payloads


def extract_tag120_json(data: bytes) -> dict[str, Any] | None:
    """Return the first decoded tag 120 JSON payload found in ``data``."""
    key = MISB0601Encoder.MISB_0601_KEY
    start = data.find(key)
    while start != -1:
        try:
            for tag, value in iter_local_set_items(data[start:]):
                if tag == MISB0601Encoder.TAG_AION_TELEMETRY_JSON:
                    decoded = json.loads(value.decode("utf-8"))
                    if not isinstance(decoded, dict):
                        raise KlvParseError("tag 120 JSON payload is not an object")
                    return decoded
        except KlvParseError:
            next_start = data.find(key, start + 1)
            if next_start == -1:
                raise
            start = next_start
            continue
        start = data.find(key, start + 1)
    return None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="klv-tag120",
        description="Read KLV bytes from stdin and print AION tag 120 JSON.",
    )
    parser.add_argument("--all", action="store_true", help="Print every tag 120 payload as a JSON list.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum payloads to print with --all.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: read KLV bytes from stdin and print tag 120 JSON."""
    args = _parse_args(argv)
    data = sys.stdin.buffer.read()
    if not data:
        print("no input bytes on stdin", file=sys.stderr)
        return 1
    try:
        if args.all:
            payloads = extract_all_tag120_json(data)
            if args.limit is not None:
                payloads = payloads[: max(0, args.limit)]
            if not payloads:
                print("no MISB 0601 tag 120 JSON payload found", file=sys.stderr)
                return 1
            print(json.dumps(payloads, indent=2, sort_keys=True))
            return 0
        payload = extract_tag120_json(data)
    except (KlvParseError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"could not decode KLV tag 120: {exc}", file=sys.stderr)
        return 2
    if payload is None:
        print("no MISB 0601 tag 120 JSON payload found", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
