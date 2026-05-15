#!/usr/bin/env python3
"""Print ParrotForwarder AION KLV tag 120 JSON from stdin."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_repo_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "src"
    if src.is_dir():
        sys.path.insert(0, str(src))


_ensure_repo_src_on_path()

from parrot_forwarder.tools.klv_tag120 import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
