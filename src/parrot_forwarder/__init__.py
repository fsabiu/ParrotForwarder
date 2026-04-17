"""
ParrotForwarder - Real-time telemetry and video forwarding from Parrot Anafi.

The top-level re-exports are lazy (PEP 562 ``__getattr__``) so that
lightweight modules such as :mod:`parrot_forwarder.config` can be
imported on hosts without Olympe installed (dev laptops, CI). The
hardware-dependent classes are resolved only on explicit attribute
access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "2.0.0.dev0"

__all__ = ["TelemetryForwarder", "VideoForwarder", "ParrotForwarder"]


def __getattr__(name: str) -> Any:
    if name == "TelemetryForwarder":
        from .telemetry import TelemetryForwarder

        return TelemetryForwarder
    if name == "VideoForwarder":
        from .video import VideoForwarder

        return VideoForwarder
    if name == "ParrotForwarder":
        from .main import ParrotForwarder

        return ParrotForwarder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover - type-checker only
    from .main import ParrotForwarder
    from .telemetry import TelemetryForwarder
    from .video import VideoForwarder
