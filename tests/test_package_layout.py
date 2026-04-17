"""
Sanity tests covering the src/ package layout.

No hardware dependencies: the package ``__init__`` is lazy, so these
tests run on any host (including a dev laptop without Olympe).
"""

from __future__ import annotations

import importlib


def test_package_exposes_v2_version() -> None:
    pkg = importlib.import_module("parrot_forwarder")
    assert pkg.__version__.startswith("2."), (
        f"expected v2 package version, got {pkg.__version__!r}"
    )


def test_klv_encoder_importable_from_src_layout() -> None:
    module = importlib.import_module("parrot_forwarder.klv_encoder")
    assert hasattr(module, "encode_telemetry_to_klv"), (
        "klv_encoder must expose encode_telemetry_to_klv after the src/ move"
    )


def test_config_module_importable_without_olympe() -> None:
    """The config module must never pull in Olympe."""
    module = importlib.import_module("parrot_forwarder.config")
    assert hasattr(module, "load_config")
    assert hasattr(module, "reload_config")
