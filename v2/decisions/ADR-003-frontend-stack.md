# ADR-003 - Frontend stack for dashboard

**Status**: proposed
**Date**: 2026-04-17

## Context

The dashboard is a single screen: state badge, telemetry panel, video, event log, three buttons. We don't need routing, state management libraries, or a large component system. But we do need a small amount of reactivity and a sane build for hashed asset URLs.

Options:

1. **Vanilla TS + Vite**. Zero framework. Hand-write the reactivity (~a few subscribers). Ship one bundle.
2. **Svelte + Vite**. Tiny runtime, reactive declarations, no virtual DOM overhead, builds to vanilla JS.
3. **React + Vite**. Ubiquitous, verbose for a one-screen app.

## Decision

Svelte.

## Consequences

Easier:
- Reactivity without hand-rolling.
- Small bundle (< 50 KB gzipped expected).
- Anyone who knows HTML/JS can read `.svelte` files.

Harder:
- One more toolchain concept for maintainers. Balanced by the fact that the whole app is small.

## Alternatives considered

- **Vanilla TS**: fine but reactivity glue code adds up and is a minor maintenance hazard. Rejected.
- **React**: oversized for the feature set. The v2 scope doesn't justify it. Rejected.
