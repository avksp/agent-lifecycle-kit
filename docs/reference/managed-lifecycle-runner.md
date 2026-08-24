# Workflow execution

Release 2.0 makes `workflow` the single lifecycle authority. The managed
execution route is a workflow operation bound to the frozen plan, source
revision, task packet and current state revision.

## Current route

The `plan-verification` gate checks the frozen manifest, lock and packet
lineage before this route is allowed to execute.

```text
agent-lifecycle workflow run \
  --state <run.state.json> \
  --manifest <plan.manifest.json> \
  --operation-id <id> \
  --expected-revision <n> \
  --source-revision <sha>
```

The workflow owns authorization, task attempts, budgets, result freshness,
review, remediation, external actions and final-audit outcomes. The active
receipt is `agent-workflow-run-receipt.v1`; the next action is
`agent-workflow-next-action.v1`.

## What changed in 2.0

The former controlled-runner command surface is removed. Historical runner
schemas and records are still accepted only by the explicit read-only
`workflow migrate-runner-artifact` converter. They are not a fallback
execution path and cannot write workflow state.

The converter is bounded, private and no-replace. It validates source schema,
digest, size and file stability, emits `authorityClaimed: false` and
`stateWritten: false`, and never starts a host or model call.

## Adapter boundary

An adapter may help a host perform an operation, but it does not own lifecycle
state. A host-facing receipt is evidence for the workflow operation; it cannot
promote itself, bypass review or replace the frozen plan. Ordinary workflow
imports do not load compatibility migration code.

## Compatibility policy

Legacy conversion is part of every 2.x distribution. Existing historical
artifacts remain readable through the converter, while new work must use
workflow state and workflow receipts. Any future removal requires a separate
compatibility audit and is prohibited before a 3.0 decision.
