# ADR-002 - Web framework for supervisor HTTP

**Status**: proposed
**Date**: 2026-04-17

## Context

We need HTTP + WebSocket + static file serving, all inside the supervisor's asyncio loop. Options in the Python asyncio ecosystem today:

1. **FastAPI + uvicorn** - largest ecosystem, pydantic for validation, auto OpenAPI, first-class WebSocket.
2. **aiohttp** - battle-tested, no dependencies beyond stdlib-adjacent, but no schema-driven validation and no free OpenAPI.
3. **Starlette raw** - what FastAPI wraps; less magic, more manual routing and validation.

## Decision

FastAPI + uvicorn.

## Consequences

Easier:
- Pydantic already in use for config; reusing it for request/response schemas avoids a second validator.
- Auto OpenAPI for `docs/openapi.yaml`.
- WebSocket and Server-Sent Events both ergonomic.

Harder:
- Extra deps (fastapi, starlette, uvicorn, pydantic). Acceptable cost; we already ship pydantic.
- FastAPI does some magic with dependency injection; keep injection shallow in this project.

## Alternatives considered

- **aiohttp**: reliable but we'd hand-roll OpenAPI and validation. Rejected.
- **Starlette raw**: viable, but FastAPI's OpenAPI alone pays for the added surface area. Rejected.
