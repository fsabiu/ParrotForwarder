"""
Sanity tests covering the src/ package layout introduced in T01.

These tests check that:
  1. The package metadata is well-formed (``__version__`` present).
  2. The KLV encoder still imports cleanly from the new
     ``src/parrot_forwarder/`` location.

On hosts without Olympe installed (e.g. a developer laptop), we skip
rather than fail; importing ``parrot_forwarder`` triggers Olympe through
the package's ``__init__.py`` re-exports, and Olympe is Linux-only.
"""

from __future__ import annotations

import importlib

import pytest


def _olympe_available() -> bool:
    try:
        import olympe  # noqa: F401
    except Exception:
        return False
    return True


needs_olympe = pytest.mark.skipif(
    not _olympe_available(),
    reason="Olympe is not installed on this host (Linux-only). Run on the target.",
)


@needs_olympe
def test_package_exposes_version() -> None:
    """The package declares a ``__version__`` attribute after the src/ move."""
    pkg = importlib.import_module("parrot_forwarder")
    assert hasattr(pkg, "__version__"), "parrot_forwarder must expose __version__"


@needs_olympe
def test_klv_encoder_importable_from_src_layout() -> None:
    """The KLV encoder must be reachable via the package path on the new layout."""
    module = importlib.import_module("parrot_forwarder.klv_encoder")
    assert hasattr(module, "encode_telemetry_to_klv"), (
        "klv_encoder must expose encode_telemetry_to_klv after the src/ move"
    )
