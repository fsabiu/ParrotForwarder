# START prompt - begin work on ParrotForwarder v2

Paste the block below into a fresh Claude Code / Codex session. It is self-contained and does not depend on any prior conversation. It is the entry point for any agent taking the first swing at v2 work.

---

```
You are contributing to ParrotForwarder v2, an autonomous drone video/telemetry forwarder with a local web dashboard.

Project root: the ParrotForwarder git repo. The v2 branch is where all v2 work happens. Before writing any code, do the following in order:

1. Read, in full:
   - v2/README.md
   - v2/PLAN.md
   - v2/ROADMAP.md
   - v2/architecture/overview.md
   - v2/architecture/state-machine.md
   - v2/architecture/api-contract.md
   - v2/specs/01-supervisor.md
   - v2/specs/02-config.md
   - v2/specs/05-testing.md

2. Read the v1 code to understand what you are extending:
   - ParrotForwarder.py (entry shim)
   - parrot_forwarder/cli.py, main.py, telemetry.py, video.py, klv_encoder.py
   - parrot_forwarder.service (systemd unit)
   - README.md (section "Installation" and "Architecture")

3. Read v2/STATUS.md. Find the first task with status `todo` whose dependencies are all `done`. That is your task.

4. Open v2/tasks/T<NN>-<title>.md for that task. Internalize the acceptance criteria and file list.

5. Before writing code:
   - Update v2/STATUS.md: change the task's status from `todo` to `in-progress`, fill in `owner`, and add `started_at` (today's date).
   - If the task has open decisions that block it (an ADR in `proposed` state referenced by the task), resolve the ADR first by filing a concrete proposal.

6. Implement the task. Constraints that apply to all tasks:
   - Python 3.11. Do not bump protobuf above 3.20.3; Olympe's transitive 3.7.1 must be force-reinstalled to 3.20.3.
   - System GStreamer only; never Conda gstreamer.
   - All runtime logs are structured JSON at INFO or above in production; DEBUG allowed locally.
   - Follow the code layout described in v2/tasks/T01-project-skeleton.md even if T01 is not yet done (bring the affected files into that layout as you touch them).
   - Every public function in new modules has a docstring and type hints.
   - Write tests alongside the code, in the structure prescribed by v2/specs/05-testing.md. Unit + integration; do not skip either.
   - No new dependencies without updating pyproject.toml and justifying in the task or an ADR.
   - Commits are small and atomic. Push to branch `v2`.

7. When the task is done:
   - Run the "How to verify" commands in the task file. They must pass.
   - Open a PR against `v2` (or against `main` if you are merging all of v2 in T20).
   - Update v2/STATUS.md: set status `done`, paste the PR link.
   - Add a dated line to the `## Log` section in STATUS.md summarizing what changed.

8. If you get stuck:
   - If the blocker is a decision, file or update the relevant ADR and mark the task `blocked` with a `## Blocker` section referencing the ADR.
   - If the blocker is external (hardware, credentials, account access), mark `blocked` and describe what's needed.
   - Never silently abandon a task. Always leave STATUS.md truthful.

Ground rules for what v2 is trying to be:

- Autonomous. No manual resets. Power-cycle the drone, unplug the USB - the service heals itself within seconds, visibly on the dashboard.
- Observable. Operator opens http://localhost:8080 and knows exactly what's happening.
- Testable without hardware. The mock drone + mock GStreamer paths must work in CI.
- Professional. Structured logs, OpenAPI, ADRs, CI gates, typed code, concrete acceptance criteria per task.

Your first response: output the task ID you picked from STATUS.md and a one-paragraph plan for tackling it. Then begin.
```
