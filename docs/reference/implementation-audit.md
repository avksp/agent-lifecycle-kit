# Implementation audit

Implementation audit turns the `audit-plan-implementation` procedure into a
typed CLI surface. It is used after a worker submits a task result and an
independent review, before the controller accepts the task.

## Commands

Task-level audit:

```bash
agent-lifecycle audit implementation \
  --manifest work/plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

Run-level aggregation:

```bash
agent-lifecycle audit final-implementation \
  --manifest work/plans/package/plan.manifest.json \
  --state run.state.json \
  --report work/WS-01/attempt-1/implementation-audit.json \
  --out final/final-implementation-audit.json
```

The task command emits `agent-implementation-audit-report.v1`. The final command
emits `agent-final-implementation-audit.v1`.

## Audit a plan package

When one person hands a plan and its implementation to another, audit the
package directory as one unit:

```bash
agent-lifecycle audit package \
  --plan-dir tasks/release-1-63 \
  --state work/release-1-63/run.state.json \
  --base main \
  --require-frozen \
  --require-implementation \
  --strict \
  --out work/release-1-63/evidence/package-audit.json
```

`--plan-dir` discovers the canonical plan files. With `--state`, the command
discovers canonical implementation-audit reports below the state artifact
directory. Use repeatable `--report <path>` options when the reviewer wants an
explicit report list. Use the command without `--state` for plan-only review.

The command emits `agent-plan-package-audit-report.v1` with three useful
statuses: `PASS` means that the requested plan and implementation checks pass;
`REVIEW_REQUIRED` means that the package is inspectable but a stage is not
complete, such as a draft plan or missing state; `FAIL` contains concrete
blockers. `--strict` turns a non-PASS result into a CI or handoff error after
the receipt is written.

## What is checked

The task report is a deterministic facade over existing lifecycle contracts:

- frozen plan status and plan digest;
- workflow state revision, task id, attempt and source revision;
- task result identity and independent review identity;
- current task-scoped Git file set and content digests, recomputed from the
  frozen source revision; caller-supplied `--path` values cannot replace this
  evidence;
- worker self-certification;
- write ownership, forbidden writes and read-only paths;
- supplied evidence paths against required evidence ids;
- sandbox evidence through `agent-sandbox-receipt.v1` when containment is
  required;
- acceptance coverage from result outcomes and review checks.

The report verdict is one of `ACCEPTED`, `REWORK`, `CONTRACT_CHANGE` or
`BLOCKED`. A task can be accepted by the workflow gate only when the report has
`status: PASS` and `verdict: ACCEPTED`.

If the report returns `REWORK` for open findings inside the frozen scope, pass
that report to `workflow task-rework --implementation-audit <path>` together
with the selected finding IDs. ALK validates its lineage and independence,
archives its identity with the current attempt, and requires a fresh result and
audit for the next attempt.

For v4 task-local outcomes, `workflow task-review-apply` is the canonical
mutation. It consumes the current task result, independent review and, when
required, implementation audit, then applies `ACCEPTED`, `REWORK`,
`CONTRACT_CHANGE` or `BLOCKED` without rewriting sibling task state.

## Workflow gates

Plans or tasks can declare implementation audit as mandatory with
`implementationAuditRequired: true` or `implementationAudit: {"required": true}`.
When mandatory:

- `workflow task-accept` rejects the task unless `--implementation-audit` points
  to an accepted report;
- `workflow run` returns a blocked next action for verifying or accepted tasks
  that still miss the report;
- `workflow finalize` rejects the run when an accepted required task has no
  accepted implementation audit report.

Runs can also require a final implementation audit with
`finalImplementationAuditRequired: true` or `implementationAudit.finalRequired:
true`. In that case, direct `workflow finalize` must include
`--final-implementation-audit`.

## Boundary

Implementation audit does not fix findings and does not refreeze a plan. Write
set, ownership or architecture gaps must be remediated inside the frozen scope
or routed back to planning. The commands do not start model calls.
