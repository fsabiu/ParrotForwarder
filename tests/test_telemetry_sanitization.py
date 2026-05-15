from __future__ import annotations

from parrot_forwarder.sanitize import jsonable


def test_jsonable_redacts_secret_mapping_fields() -> None:
    payload = {
        "wifi.security_changed": {
            "key": "plain-wifi-password",
            "key_type": "plain",
            "type": "wpa2",
        },
        "nested": {
            "api_key": "token-value",
            "refresh_token": "refresh-value",
            "safe": "visible",
        },
    }

    sanitized = jsonable(payload)

    assert sanitized == {
        "wifi.security_changed": {
            "key": "[redacted]",
            "key_type": "plain",
            "type": "wpa2",
        },
        "nested": {
            "api_key": "[redacted]",
            "refresh_token": "[redacted]",
            "safe": "visible",
        },
    }
