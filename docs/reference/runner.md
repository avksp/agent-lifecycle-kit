# Legacy runner artifacts

Release 2.0 removes the controlled runner as an active execution authority.
Durable workflow state and the `workflow` command family are the only current
execution surface.

The old runner names remain only as read-only compatibility vocabulary for
artifacts produced before 2.0. They do not start a process, mutate workflow
state, authorize a task, or claim production promotion.

## Current route

Use the workflow command and its frozen plan/state lineage:

```text
agent-lifecycle workflow run \
  --state <run.state.json> \
  --manifest <plan.manifest.json> \
  --operation-id <id> \
  --expected-revision <n> \
  --source-revision <sha>
```

Task starts, results, reviews, remediation and finalization remain workflow
operations. A legacy runner document cannot authorize any of them.

## Read-only migration

To preserve an old artifact for inspection, use the explicit converter:

```text
agent-lifecycle workflow migrate-runner-artifact \
  --input <legacy-runner-artifact.json> \
  --output <conversion.json>
```

The converter performs a bounded read, validates the historical schema and
self-digest, preserves the source bytes, and writes a private no-replace
conversion record. The conversion is non-authoritative: it sets
`authorityClaimed` and `stateWritten` to `false`, does not launch a host, and
does not call a model or network.

Supported historical schema IDs are registered in
`agent_lifecycle.contracts.legacy_runner_schemas`. Unknown, oversized,
malformed, stale or symlink-backed inputs fail closed. The migration boundary
fails closed for unsupported authority claims.

## Compatibility boundary

The compatibility converter is required throughout the 2.x line. It is not a
second workflow engine and it must not be imported by ordinary workflow
execution. Removing it requires a separate compatibility audit and is not
permitted before a future 3.0 decision.
