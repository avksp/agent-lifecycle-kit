# CLI Reference

The CLI prints JSON for machine-readable commands. Commands that mutate state
record receipts or require explicit input files; diagnostic commands stay
read-only unless their own help says otherwise.

## Foundation

- `agent-lifecycle version`: print package version.
- `agent-lifecycle schema list`: list known public schemas.
- `agent-lifecycle schema show <schema-id>`: print one schema.
- `agent-lifecycle contract policy/check`: inspect public compatibility policy.

## Planning

- `agent-lifecycle specification check`: validate specification shape.
- `agent-lifecycle plan check`: validate a plan manifest and optional lock.
- `agent-lifecycle plan snapshot/reconcile/handoff`: maintain compact,
  reviewable plan state.
- `agent-lifecycle import plan/check`: keep imported work draft-only until
  reviewed.

## Execution

- `agent-lifecycle workflow task-start`: open a bounded task attempt.
- `agent-lifecycle workflow task-result`: submit implementation evidence.
- `agent-lifecycle workflow task-accept`: accept a completed task.
- `agent-lifecycle workflow block/resolve-blocker`: record external blockers.
- `agent-lifecycle workflow finalize`: produce final lifecycle proof.
- `agent-lifecycle runner start/status/transition/stop/resume`: control
  bounded execution state.

## Review And Quality

- `agent-lifecycle audit review-check`: validate review verdicts.
- `agent-lifecycle quality pack-check`: validate optional quality packs.
- `agent-lifecycle quality behavior-check`: run fixture-backed behavior checks.
- `agent-lifecycle metrics cost-check`: validate lifecycle cost receipts.

## Context And Continuity

- `agent-lifecycle context check/render`: validate and render compact context.
- `agent-lifecycle goal check/summarize/update`: keep user intent traceable.
- `agent-lifecycle followup check/add/close/sweep`: track deferred work.
- `agent-lifecycle worktree policy-check/receipt/check`: verify write-scope and
  attempt isolation.

## Adapters

- `agent-lifecycle adapter validate`: check a descriptor against the baseline.
- `agent-lifecycle adapter inspect`: inspect source projection and safe host
  command surfaces.
- `agent-lifecycle adapter scaffold`: create an `EXPERIMENTAL` adapter
  skeleton.
- `agent-lifecycle adapter install-plan`: preview host setup without writes.
- `agent-lifecycle adapter event-check`: validate event capture receipts.

## Diagnostics And Evidence

- `agent-lifecycle diagnose`: build one redacted checkout readiness report.
- `agent-lifecycle diagnostics bundle`: collect selected evidence into a
  redacted bundle.
- `agent-lifecycle report status-view`: render a compact status view.
- `agent-lifecycle evidence index/search`: build and query compact evidence
  indexes.
- `agent-lifecycle model profile-check/route/usage-check`: validate routing and
  usage receipts.

Use `--help` on any command group for exact arguments.
