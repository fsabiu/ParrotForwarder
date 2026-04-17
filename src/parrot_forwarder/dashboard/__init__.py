"""
Dashboard bundle served from the supervisor at ``/``.

v2 ships a vanilla HTML/JS placeholder (see ``static/index.html``) that
consumes the documented REST + WebSocket contract. A Svelte rewrite is
tracked as follow-up work per ADR-003.
"""

from __future__ import annotations

from pathlib import Path


def static_dir() -> Path:
    """Return the filesystem path to the bundled dashboard assets."""
    return Path(__file__).resolve().parent / "static"
