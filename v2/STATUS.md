# v2 Status

This file is the single source of truth for v2 progress. Update it whenever a task changes status. Agents resuming work should read this first.

**Format rule**: status is one of `todo`, `in-progress`, `blocked`, `done`. When marking `in-progress`, set `current_owner` and `started_at`. When marking `done`, add the PR link.

## Current phase

Phase 0 - Foundation.

## Current focus

Planning complete. No code tasks in flight yet.

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
| T01 | Project skeleton + pyproject | 0 | todo | - | See [tasks/T01-project-skeleton.md](tasks/T01-project-skeleton.md) |
| T02 | Config loader (YAML + env + CLI) | 0 | todo | - | |
| T03 | Mock drone backend for tests | 0 | todo | - | |
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
