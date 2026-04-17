# Tasks

Atomic, ordered work items. Status lives in [../STATUS.md](../STATUS.md) - each change to this folder must be reflected there.

## Task file format

Each task has its own file with:

```markdown
# T<NN> - <title>

**Phase**: <0-4>
**Depends on**: T<NN>, T<NN>
**Estimated effort**: <S|M|L>  (S <1 day, M 1-3 days, L 3-7 days)

## Goal
One paragraph.

## Acceptance criteria
Bulleted list of things that must be true when done.

## Files touched
Concrete paths where changes should land.

## How to verify
Command(s) the agent/reviewer runs to confirm.

## Notes
Anything that isn't obvious from the spec.
```

## Rules

1. Tasks are atomic. If a task doesn't fit in one PR, split it.
2. Tasks declare dependencies. An agent should not start a task whose dependencies are not `done`.
3. When starting a task, update STATUS.md: set status `in-progress`, set owner, set `started_at`.
4. When finishing, update STATUS.md: set `done`, add PR link.
5. If blocked, set status `blocked` and add a `## Blocker` section in the task file explaining what's needed.
