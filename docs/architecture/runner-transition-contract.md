# Workflow transition contract

Release 2.0 replaces the former controlled-runner transition surface with the
workflow state machine. The durable workflow state is the single authority for
authorization, task attempts, budgets, result acceptance, remediation and
finalization.

## Current authority

Current mutations use workflow commands and carry operation id, expected state
revision, source revision and frozen-plan lineage. The active execution receipt
is `agent-workflow-run-receipt.v1`.

The former runner action names remain in a read-only compatibility catalog so
callers receive a stable replacement or migration route. The catalog is not a
dispatcher and it cannot mutate state.

## Historical boundary

Pre-2.0 runner state, transition, snapshot and recovery documents are historical
artifacts. `workflow migrate-runner-artifact` validates and converts them with
bounded input, source immutability, private no-replace output and
`authorityClaimed: false`. It never reconstructs missing lineage or grants
execution authority.

The compatibility converter is required throughout 2.x. Its removal needs an
independent compatibility audit and a future major-version decision; no 2.x
minor release may reintroduce a second execution authority.
