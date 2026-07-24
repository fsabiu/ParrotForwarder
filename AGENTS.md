# ParrotForwarder Agent Instructions

Read root governance first:

1. `../PROJECT.md`
2. `../CONTRIBUTING.md`
3. `../work-packages/WP-03-parrot-forwarder/README.md`, `PLAN.md`, and `EVIDENCE.md`

Local scope: WP-03. Create a short-lived task branch from the current
`ParrotForwarder:e2e` head, open a PR back to `e2e`, and record validation in
the WP evidence file before review. The Pully AION PR agent checks eligible
PRs on its five-minute cycle.

Develop locally or in a dedicated Gonzalo workspace outside the deployed e2e,
V1, and demo roots defined by root governance. Never use a deployed runtime
root as an agent workspace, Git checkout, source-edit, build, or test location.

After a ParrotForwarder PR lands, update the root AION-Ops submodule pointer to the exact merged `ParrotForwarder:e2e` commit. Do not mark the work complete until that pointer follow-up exists or is explicitly documented as not needed.

Local checks are listed in `CLAUDE.md`. Keep this file as a concise pointer only.
