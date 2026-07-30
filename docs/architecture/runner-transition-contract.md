# Runner transition contract

The runner defines a provider-neutral state machine that controls task
execution decisions without replacing workflow state.

## Ownership

- Workflow state remains authoritative for lifecycle phase, task status,
  blockers, acceptance and finalization.
- Runner state owns only execution-loop progress: current task, runner
  revision, bounded counters, stop requests, transition history and applied
  operation ids.
- Host adapters execute capabilities and produce receipts. They do not own the
  runner transition table.

## Transition table

| From | Allowed actions |
| --- | --- |
| `READY` | `attempt`, `block`, `abort` |
| `ATTEMPTING` | `validate`, `reroute`, `block`, `abort` |
| `VALIDATING` | `review`, `remediate`, `reroute`, `block`, `abort` |
| `REVIEWING` | `accept`, `remediate`, `reroute`, `split`, `block`, `abort` |
| `WAITING_REMEDIATION` | `attempt`, `block`, `abort` |
| `WAITING_REROUTE` | `attempt`, `block`, `abort` |
| `WAITING_SPLIT` | `block`, `abort` |
| `BLOCKED` | `abort` |
| `STOPPED` | `resume` |
| `COMPLETE` | terminal |
| `ABORTED` | terminal |

Every mutating command carries an operation id and expected runner revision.
Duplicate operations and stale revisions fail closed.

## Resource rules

The runner policy bounds:

- attempts per task;
- reroutes per task;
- splits per task;
- billable tokens recorded by transition requests.

When any cap would be exceeded, the transition is rejected before state is
written.

## Patch restoration

Remediation may reference patch metadata, but the runner only accepts it when:

- the patch reports `status: PASS`;
- the patch has a content digest;
- every changed file is inside the task write scope from workflow state.

The runner validates patch metadata. It does not apply patches itself and does
not bypass ownership checks.

## Context rule

`agent-runner-snapshot.v1` is the compact continuation view. It carries runner
status, next allowed actions, budget counters, lineage and recent transitions.
It must fit the selected small-context profile. Larger models can still inspect
the full runner state, workflow state, evidence and reviews.
