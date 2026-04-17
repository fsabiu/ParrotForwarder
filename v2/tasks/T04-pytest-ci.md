# T04 - pytest skeleton and CI

**Phase**: 0
**Depends on**: T01
**Estimated effort**: S

## Goal

Stand up the test runner, linter, and CI. Establish markers and conventions so later tasks drop tests in without re-deciding.

## Acceptance criteria

- `pytest.ini` (or `[tool.pytest.ini_options]` in pyproject) configures test discovery under `tests/`, registers markers `live` and `slow`.
- `conftest.py` at `tests/conftest.py` with shared fixtures (empty initially, ready to add to).
- `ruff.toml` with a starter config. Line length 100. Fail CI on lint errors.
- `mypy.ini` with `strict = True` for `src/parrot_forwarder/` (allow missing imports for olympe, gstreamer).
- `.github/workflows/ci.yml` runs on push and PR:
  - Checkout, setup Python 3.11, install `-e .[dev]` (or `requirements-dev.txt`).
  - `ruff check .`
  - `mypy src/`
  - `pytest -m "not live and not slow"`
- CI passes with empty/placeholder tests.

## Files touched

- `pyproject.toml` (pytest + ruff config sections) or separate `pytest.ini` / `ruff.toml`
- `tests/conftest.py`
- `.github/workflows/ci.yml`
- `mypy.ini`

## How to verify

Push a branch, watch the Actions tab - green check.

## Notes

- Use `actions/setup-python@v5` with `cache: pip`.
- Ubuntu 24.04 runner (`ubuntu-24.04`). Do not use `ubuntu-latest` - it floats.
