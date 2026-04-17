"""
Test helpers for ParrotForwarder v2.

This subpackage is importable on any host (it has no runtime dependency
on Olympe, GStreamer, or a physical drone) and is exported so downstream
projects can reuse the mocks.
"""

from __future__ import annotations

from .mock_drone import MockDrone, MockSubscription

__all__ = ["MockDrone", "MockSubscription"]
