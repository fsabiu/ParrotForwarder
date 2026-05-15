"""Sanitizers for telemetry payloads that may include SDK raw state."""

from __future__ import annotations

import math
from collections.abc import Mapping

_MISSING = object()
_REDACTED = "[redacted]"
_SECRET_FIELD_NAMES = {
    "access_token",
    "api_key",
    "key",
    "password",
    "passphrase",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}


def redact_mapping_key(key: object) -> bool:
    name = str(key).strip().lower()
    return (
        name in _SECRET_FIELD_NAMES
        or name.endswith("_key")
        or name.endswith("_password")
        or name.endswith("_secret")
        or name.endswith("_token")
    )


def jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None

    enum_name = getattr(value, "name", None)
    if isinstance(enum_name, str) and enum_name:
        return enum_name

    if isinstance(value, Mapping):
        return {
            str(key): _REDACTED if redact_mapping_key(key) else jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(item) for item in value]

    enum_value = getattr(value, "value", _MISSING)
    if isinstance(enum_value, (str, int, float, bool)) or enum_value is None:
        return enum_value

    return str(value)
