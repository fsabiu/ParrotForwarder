# ParrotForwarder v2

Planning and design artifacts for v2 of ParrotForwarder.

## Why v2

v1 is a bare CLI daemon: no operator visibility, no remote control, no recovery from real-world failure modes beyond simple Olympe reconnect. Running it requires SSH into the host, staring at journald, and restarting by hand when the pipeline wedges.

v2 turns ParrotForwarder into an autonomous, supervised service with a local-only web dashboard, a REST + WebSocket control surface, structured telemetry, and a test harness that doesn't require a physical drone.

## What's in this folder

| File | Purpose |
|---|---|
| [PLAN.md](PLAN.md) | Master plan - goals, scope, non-goals, constraints |
| [ROADMAP.md](ROADMAP.md) | Phased delivery with milestones |
| [STATUS.md](STATUS.md) | Live progress tracker - updated as tasks complete |
| [architecture/](architecture/) | System design, state machine, API contract, data flow |
| [specs/](specs/) | Feature specs (one file per feature) |
| [tasks/](tasks/) | Atomic, ordered work items with status |
| [decisions/](decisions/) | Architecture Decision Records (ADRs) |
| [prompts/](prompts/) | Self-contained prompts to start or resume v2 work |

## Starting work

- **Fresh start (no prior context)**: read [prompts/START.md](prompts/START.md).
- **Resuming work**: read [prompts/RESUME.md](prompts/RESUME.md).

Both prompts drive from the files in this folder. They do not depend on any prior conversation.

## Branch

All v2 work happens on the `v2` branch of [github.com/fsabiu/ParrotForwarder](https://github.com/fsabiu/ParrotForwarder). Keep `main` as the v1 reference until v2 is ready to merge.
