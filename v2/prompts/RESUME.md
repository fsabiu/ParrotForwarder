# RESUME prompt - continue work on ParrotForwarder v2

Paste the block below into a fresh Claude Code / Codex session. It reconstructs context entirely from files in the repo - it does not require conversation history.

---

```
You are resuming work on ParrotForwarder v2. A previous session may or may not have made progress; the truth is in the files on the v2 branch, not in any conversation log.

Project root: the ParrotForwarder git repo, branch `v2`. Work exclusively on that branch unless explicitly told otherwise.

Step 1 - Reconstruct state.

Read, in this order:

1. v2/STATUS.md - the source of truth for progress, current phase, in-flight tasks, blockers, and the log.
2. Any task in STATUS.md with status `in-progress` - read v2/tasks/T<NN>-<title>.md for that task.
3. Any task with status `blocked` - read it and the ADR or note it references.
4. v2/PLAN.md, v2/ROADMAP.md if you need context on where things fit.
5. Architecture and spec files that the in-progress task references.

Step 2 - Verify the repo matches STATUS.md.

- Run `git log --oneline -20` and `git status`.
- Check the last few commits. Do they correspond to the tasks marked `done`?
- If there's drift (code exists for a task marked `todo`, or a task marked `done` has no corresponding PR merge), fix STATUS.md first to match reality. Log the correction in the `## Log` section.

Step 3 - Pick what to do.

Priority order:

a. Unblock any `blocked` task whose blocker has been resolved (ADR now `accepted`, hardware available, etc.). Change status to `in-progress` and proceed.
b. Continue any `in-progress` task. Read its file; check git diff for what's already been done; pick up where it left off.
c. If nothing is in-progress and nothing is unblocked, find the first `todo` task whose dependencies are all `done` and start it per v2/prompts/START.md step 5 onward.

Step 4 - Before modifying anything, state your plan.

Output:
- The task ID you are picking up.
- A one-paragraph summary of what STATUS.md says about its current state.
- A one-paragraph plan for the next step (finish the task, unblock it, etc.).
- Any corrections you made to STATUS.md in Step 2.

Then proceed.

Constraints identical to START.md apply:
- Python 3.11, protobuf 3.20.3, system GStreamer.
- Structured JSON logs, typed code, tests alongside code.
- STATUS.md stays truthful. Every status change is accompanied by a commit.
- No silent abandonment - if you hit a blocker, mark it explicitly.

Ground rules for v2 identity (unchanged from START.md):
- Autonomous: no manual resets.
- Observable: dashboard at localhost shows truth.
- Testable without hardware: mock-drone CI path must work.
- Professional: ADRs for decisions, OpenAPI, CI gates.

One final rule specific to RESUME: do not re-litigate decisions already recorded as `accepted` in v2/decisions/. If you disagree, file a new ADR that supersedes the old one; do not unilaterally change direction mid-task.
```
