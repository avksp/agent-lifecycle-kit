# Implementation audit

Implementation audit turns the `audit-plan-implementation` procedure into a
typed CLI surface. It is used after a worker submits a task result and an
independent review, before the controller accepts the task.

## Commands

Task-level audit:

```bash
agent-lifecycle audit implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

Run-level aggregation:

```bash
agent-lifecycle audit final-implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --report work/WS-01/attempt-1/implementation-audit.json \
  --out final/final-implementation-audit.json
```

The task command emits `agent-implementation-audit-report.v1`. The final command
emits `agent-final-implementation-audit.v1`.

## What is checked

The task report is a deterministic facade over existing lifecycle contracts:

- frozen plan status and plan digest;
- workflow state revision, task id, attempt and source revision;
- task result identity and independent review identity;
- worker self-certification;
- write ownership, forbidden writes and read-only paths;
- supplied evidence paths against required evidence ids;
- sandbox evidence through `agent-sandbox-receipt.v1` when containment is
  required;
- acceptance coverage from result outcomes and review checks.

The report verdict is one of `ACCEPTED`, `REWORK`, `CONTRACT_CHANGE` or
`BLOCKED`. A task can be accepted by the workflow gate only when the report has
`status: PASS` and `verdict: ACCEPTED`.

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
