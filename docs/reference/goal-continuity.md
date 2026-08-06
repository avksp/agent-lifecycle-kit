# Goal continuity

`agent-goal-record.v1` is an optional lifecycle-adjacent artifact for long
tasks. It records the user intent, owner-visible outcome, constraints, evidence
ids and workflow lineage needed to resume the task without replaying long chat
history.

The record is not a second workflow state machine. The workflow state remains
authoritative for phase, task status, blockers and finalization. A goal record
is valid only when its lineage matches the current state.

## Commands

```bash
agent-lifecycle goal check --record <goal-record.json> --state <run.state.json> --current
agent-lifecycle goal summarize --record <goal-record.json> --state <run.state.json> --profile profiles/small-context-profile.v1.json --target-window 8k
agent-lifecycle goal view --record <goal-record.json> --state <run.state.json> --usage-receipt <usage.json> --change-summary <changes.json>
agent-lifecycle goal update --record <goal-record.json> --state <run.state.json> --status READY_FOR_FINALIZATION --evidence-id <evidence-id> --reason "<reason>" --out <goal-record.updated.json>
```

`goal summarize` emits `agent-objective-snapshot.v1`. The snapshot carries the
concise intent, owner outcome, constraints, digests, evidence ids and the next
workflow action instead of duplicating the full record or conversation. It is
validated against the same small-context profile used by task packets,
including `4k-strict`, so small local models can continue with a bounded
working set.

The compact snapshot is not a quality downgrade for larger models. Larger
models can still inspect the full plan, workflow state, evidence, reviews and
final audit. The snapshot only reduces continuation overhead; acceptance,
audits and final proof remain tied to the authoritative artifacts.

## Goal and progress view

`goal view` emits `agent-goal-progress-view.v1`. It combines the goal record,
the current workflow phase, next action, task status counts, lifecycle progress
rows, optional attested token usage and optional Git-style change counters.

Use JSON when another tool should consume the view:

```bash
agent-lifecycle goal view \
  --record <goal-record.json> \
  --state <run.state.json> \
  --usage-receipt <usage.json> \
  --change-summary <changes.json> \
  --out work/run/goal-progress-view.json
```

Use `--terminal` for a human-readable summary:

```bash
agent-lifecycle goal view \
  --record <goal-record.json> \
  --state <run.state.json> \
  --terminal
```

The command is read-only. It does not write workflow state, does not update the
goal record, does not start host CLIs and does not make model calls. Unknown or
unattested token usage is displayed as `↑?/↓? tok`.

`workflow finalize` accepts an optional `--goal-record <goal-record.json>`.
When supplied, the record must match the same run, package, plan revision, plan
digest, source revision, state revision and `completionCheck` identity before
the final proof is written.

## Fail-closed rules

Validation fails when:

- the record has an unsupported schema version;
- required intent, outcome, constraints, lineage or status fields are missing;
- lineage points at another run, package, plan digest or source revision;
- `--current` is used and `lineage.stateRevision` does not match workflow
  state;
- the record's `completionCheck` identity differs from the current workflow
  state.

This fails closed and keeps continuation cheap and traceable without accepting
stale or contradictory task intent.
