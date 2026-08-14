# Long-term project governance

ALK is designed for repeated work on one repository. Each task still has its
own specification, reviewed plan, lock, execution evidence and final proof;
project-level context helps those task plans remain consistent over time.

## Recommended sequence

1. Record stable project principles in a small JSON artifact.
2. Reference the artifact from the local project profile by path and digest.
3. Create and independently review the task specification and plan.
4. Freeze the plan and create its matching lock.
5. When the scope changes, compare the old and new plans with `plan delta`.
6. Re-review and regenerate the lock when implementation authority changes.
7. Continue execution only after the normal ALK adoption and audit gates pass.

This keeps project context, task authority and implementation evidence separate.
It also makes a handover explainable: the next operator can inspect principles,
the plan delta and the new reviewed plan instead of reconstructing decisions
from a long conversation.

## What remains authoritative

Project principles are defaults and constraints. They do not approve a task,
grant a write path or replace acceptance criteria. The frozen plan and lock
remain the authority for the current change. A plan delta describes a possible
transition; it never applies that transition.

The repository remains the durable record of source, tests, documentation and
plan packages. ALK receipts bind those artifacts to the run and make missing
or contradictory evidence visible.

## Handover example

Give the next reviewer:

- the current project-principles artifact and its digest;
- the previous and current plan manifests;
- the old and new locks;
- the generated plan delta;
- the independent review and implementation evidence.

The reviewer can run `project principles check`, `plan delta-check` and the
normal plan and lock checks before deciding whether work may continue.
