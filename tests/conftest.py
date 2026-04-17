"""
pytest configuration for ParrotForwarder.

The files in this directory that ship with v1 are standalone diagnostic
scripts (they each define a ``main()`` and import Olympe at module level),
not pytest tests. They are not discoverable on hosts without a drone or
without Olympe installed, so we keep them in place for manual runs but
exclude them from pytest's auto-collection.

The v2 pytest skeleton (T04) will add real unit/integration tests under
``tests/unit/`` and ``tests/integration/``; those directories remain
discoverable.
"""

from __future__ import annotations

# Files that are executable scripts requiring a live drone and/or Olympe.
collect_ignore_glob = [
    "test_drone_connection.py",
    "test_klv_receiver.py",
    "test_mediamtx_integration.py",
    "test_telemetry_receiver.py",
    "test_video_receiver.py",
    "test_video_sender.py",
    "test_video_stream.py",
    "run_tests.py",
]
