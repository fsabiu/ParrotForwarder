# v2 Status

This file is the single source of truth for v2 progress. Update it whenever a task changes status. Agents resuming work should read this first.

**Format rule**: status is one of `todo`, `in-progress`, `blocked`, `done`. When marking `in-progress`, set `current_owner` and `started_at`. When marking `done`, add the PR link.

## Current phase

Phase 0 - Foundation.

## Current focus

T01-T03 done. T04 (pytest skeleton + CI) is next.

## Phase progress

| Phase | Status | Notes |
|---|---|---|
| 0 - Foundation | todo | See task T01-T05 below |
| 1 - Supervisor | todo | |
| 2 - REST API | todo | |
| 3 - Dashboard | todo | |
| 4 - Tests/docs/packaging | todo | |

## Task progress

| ID | Title | Phase | Status | Owner | Notes |
|---|---|---|---|---|---|
| T01 | Project skeleton + pyproject | 0 | done | claude (fsabiu) | src/ layout + pyproject. Merged directly to v2. |
| T02 | Config loader (YAML + env + CLI) | 0 | done | claude (fsabiu) | pydantic v2 model, layered precedence, reload policy. Merged directly to v2. |
| T03 | Mock drone backend for tests | 0 | done | claude (fsabiu) | MockDrone + drone_factory DI on ParrotForwarder. Merged directly to v2. |
| T04 | pytest skeleton + CI | 0 | todo | - | |
| T05 | install.sh + Makefile | 0 | todo | - | |
| T06 | Supervisor state machine | 1 | todo | - | |
| T07 | Forwarder subprocess + IPC | 1 | todo | - | |
| T08 | Health monitor (Olympe + GStreamer) | 1 | todo | - | |
| T09 | Structured JSON logging | 1 | todo | - | |
| T10 | REST API (FastAPI) | 2 | todo | - | |
| T11 | WebSocket events + telemetry | 2 | todo | - | |
| T12 | Prometheus metrics | 2 | todo | - | |
| T13 | Dashboard SPA skeleton | 3 | todo | - | |
| T14 | Video preview (HLS or WebRTC) | 3 | todo | - | |
| T15 | Dashboard -> REST/WS wiring | 3 | todo | - | |
| T16 | Integration test harness | 4 | todo | - | |
| T17 | E2E smoke test | 4 | todo | - | |
| T18 | Runbook + dev guide | 4 | todo | - | |
| T19 | Dockerfile + USB passthrough docs | 4 | todo | - | |
| T20 | Release 2.0.0 | 4 | todo | - | |

## Open decisions

| ADR | Topic | Status |
|---|---|---|
| ADR-001 | Supervisor architecture (threads vs subprocess vs systemd template) | proposed |
| ADR-002 | Web framework (FastAPI vs aiohttp) | proposed |
| ADR-003 | Frontend stack (vanilla vs Svelte vs React) | proposed |
| ADR-004 | Video preview transport (HLS vs WebRTC vs MJPEG) | proposed |

## Known blockers

None.

## Log

- **2026-04-17** - Branch `v2` created. Planning docs, roadmap, task list, ADR placeholders written. No code changes yet.
- **2026-04-17** - T01 complete. Moved `parrot_forwarder/` to `src/parrot_forwarder/` via `git mv` (history preserved). Added `pyproject.toml` with `setuptools>=68` build backend, `parrot-forwarder = parrot_forwarder.cli:main` console script, direct deps (`parrot-olympe==0.0.0`, `protobuf==3.20.3`, `PyYAML`), `[project.optional-dependencies].dev` group, and pytest/ruff/mypy tool config. Added `requirements-dev.txt` mirroring the dev group. `ParrotForwarder.py` trimmed to the 3-line shim. `tests/conftest.py` excludes the v1 Olympe-dependent diagnostic scripts from pytest auto-collection so `pytest tests/` runs cleanly on any host. `tests/test_package_layout.py` added as a sanity test (skipped when Olympe is not installed). README install section rewritten around `pip install -e .`. `.gitignore` already covers `build/`, `dist/`, `*.egg-info/`. Full verification (`pip install -e . -r requirements-dev.txt` and `parrot-forwarder --help`) requires the Linux target (Olympe is Linux-only and not available on the dev Mac); pyproject shape and src-layout imports verified locally.
- **2026-04-17** - T02 complete. Added `src/parrot_forwarder/config.py` (pydantic v2 `Config` model mirroring `v2/specs/02-config.md`; `load_config(path, env, cli_overrides)` applies the layered precedence defaults<yaml<env<cli with no module-import side effects; `reload_config(old, new)` returns a `ReloadResult` - all-or-nothing reject if any non-reloadable field changed, per spec). Env vars parsed from `PARROT_FORWARDER_A__B__C` pattern with boolean/int/float coercion. Every sub-model is frozen + `extra="forbid"` so typos produce field-qualified errors. `config.yaml.example` added with every field and inline comment. `tests/test_config.py` has 20 tests covering all six scenarios from `specs/02-config.md` plus malformed input, unknown fields, out-of-range values, and the no-side-effects invariant. Refactored `src/parrot_forwarder/__init__.py` to PEP 562 lazy re-exports so `import parrot_forwarder.config` no longer drags in Olympe; dropped the Olympe-skip in `test_package_layout.py` as a result. All 23 tests pass on Python 3.12 (Mac dev host).
- **2026-04-17** - T03 complete. Added `src/parrot_forwarder/testing/` subpackage with `MockDrone` (matches the Olympe surface actually used in v1: `connect`, `disconnect`, `get_state(MessageClass)`, `drone(MessageClass)` subscription factory) and `MockSubscription`. Controllable via `set_battery_percent`, `set_gps_fix`, `set_attitude`, `set_position`, `force_disconnect`, `fail_next_connect`, `raise_on_next_get_state`, `set_connect_delay`. Thread-safe via internal `RLock`. Added `mock_drone_factory(**defaults)` helper for DI in tests. `ParrotForwarder.__init__` now accepts `drone_factory: Callable[[str], Any]` (defaults to an internal lazy Olympe factory) and `install_signal_handlers: bool` (defaults True); the top-level `import olympe` is gone, and the `from .telemetry/.video` imports in `main.py` are now lazy inside `start_forwarding` so `import parrot_forwarder.main` works on hosts without Olympe. `tests/test_mock_drone.py` adds 18 tests covering every knob, subscription shape, thread-safety, the factory helper, and a signature check that the new DI parameter on `ParrotForwarder.__init__` is present and defaults correctly. All 41 tests pass on Python 3.12.
