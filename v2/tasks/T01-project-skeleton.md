# T01 - Project skeleton and packaging

**Phase**: 0
**Depends on**: none
**Estimated effort**: M

## Goal

Restructure the repo to a modern Python package layout and replace the ad-hoc entry point with a proper console script. No runtime behavior changes; v1's `ParrotForwarder.py` continues to work via a thin shim.

## Acceptance criteria

- `src/parrot_forwarder/` holds all package code. Existing modules move verbatim (git mv), imports updated.
- `pyproject.toml` at repo root, build system `setuptools>=68`, declares dependencies (copy from `requirements.txt`), declares console script `parrot-forwarder = parrot_forwarder.cli:main`.
- `requirements.txt` still exists for backward compat; regenerated from pyproject.
- `requirements-dev.txt` added: pytest, pytest-asyncio, ruff, mypy, httpx, pydantic.
- `pip install -e .` works in a fresh venv and installs the console script on PATH.
- Old `ParrotForwarder.py` at root becomes a 3-line shim that imports and calls the new entry point.
- `pytest tests/` still passes (even if empty - just verify pytest discovery).

## Files touched

- `pyproject.toml` (new)
- `src/parrot_forwarder/__init__.py`, `cli.py`, `main.py`, `telemetry.py`, `video.py`, `klv_encoder.py` (moved)
- `ParrotForwarder.py` (shim)
- `requirements.txt` (regenerated)
- `requirements-dev.txt` (new)
- `.gitignore` (add `build/`, `dist/`, `*.egg-info`)
- `README.md` update install section

## How to verify

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e . -r requirements-dev.txt
parrot-forwarder --help            # prints CLI usage
python ParrotForwarder.py --help   # same, via shim
pytest tests/
```

## Notes

- Keep git history for moved files (`git mv`, not copy+delete).
- Do not bump protobuf in pyproject - keep 3.20.3 pin (v1 note).
