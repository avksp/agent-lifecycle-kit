# Public contracts

Public contract policy keeps ALK outputs predictable for adapters, release
checks and operator scripts.

`agent-public-contract-policy.v1` lists the current public schemas, CLI JSON
outputs and compatibility rules. The policy is generated from the bundled
schema registry, so it is small enough for compact review and still points to
the authoritative full schemas.

```bash
agent-lifecycle contract policy --out <public-contract-policy.json>
agent-lifecycle contract check --policy <public-contract-policy.json>
```

The compatibility rules are intentionally narrow:

- public schema ids are immutable;
- existing required fields must not change meaning in-place;
- compatible additions use optional fields or a new schema id;
- deprecated input shapes remain accepted until a replacement is documented;
- CLI commands keep compact JSON envelopes with stable `schemaVersion` values;
- failures use `agent-lifecycle-error.v1` with a stable `code`.

Adapters should branch on `schemaVersion` and `code`, not prose output.
Large-model reviews can inspect the full schema body through `schema show`;
small local models can use the policy receipt as a compact map of what is
stable.

## Evidence integrity

The proof-integrity surface is additive and opt-in. It is used when a run or
final audit explicitly requires stronger evidence for a bug fix, regression or
high-risk change.

Stable schema ids:

- `agent-proof-finding.v1`
- `agent-root-cause-evidence.v1`
- `agent-fix-impact-receipt.v1`
- `agent-receipt-hash-chain.v1`
- `agent-hash-chain-migration-policy.v1`
- `agent-proof-integrity-receipt.v1`
- `agent-proof-integrity-validation.v1`

`agent-fix-impact-receipt.v1` is the canonical fix-impact contract. It binds
changed files, related finding ids, root-cause digests, behavior changes,
preserved contracts, validation evidence and collateral-damage checks.

## Sandbox boundaries

The sandbox-boundary surface is additive and opt-in for tasks that require
runtime containment evidence.

Stable schema ids:

- `agent-sandbox-receipt.v1`
- `agent-sandbox-receipt-validation.v1`
- `agent-sandbox-requirement.v1`
- `agent-sandbox-requirement-validation.v1`
- `agent-sandbox-capability.v1`
- `agent-sandbox-capability-validation.v1`

`agent-sandbox-receipt.v1` is distinct from
`agent-worktree-attempt-receipt.v1`: worktree receipts govern repository write
scope, while sandbox receipts govern runtime filesystem, network, process,
environment and enforcement-source evidence. `UNKNOWN` is a valid explicit
capability state, but high-risk required policy accepts only configured passing
sandbox statuses.

## Import interop and episode retrieval

The import interop surface maps external dialects into reviewed ALK draft
artifacts. It never treats imported content as trusted source of truth.

Stable schema ids:

- `agent-import-dialect-profile.v1`
- `agent-import-dialect-profile-validation.v1`
- `agent-episode-index.v1`
- `agent-episode-index-validation.v1`
- `agent-episode-retrieval.v1`

`agent-import-dialect-profile.v1` requires `sourceTrusted: false`,
`requiresReview: true` and `freezeBlocked: true`. Imported artifacts can carry
`nativeDialectProfileDigest`, but that digest is provenance, not review
approval.

`agent-episode-retrieval.v1` is a bounded context projection over explicit
receipt/session artifacts. Results keep artifact digests and report
`chainVerified` only when a supplied hash chain contains the same path and
digest; otherwise they are `chainUnchecked`.

## Runner recovery and optional cross-check

Runner recovery contracts are additive receipts for multi-attempt work. They do
not replace workflow state or the controlled runner state.

Stable schema ids:

- `agent-runner-attempt-snapshot-receipt.v1`
- `agent-runner-attempt-snapshot-receipt-validation.v1`
- `agent-worker-lease-receipt.v1`
- `agent-worker-lease-receipt-validation.v1`
- `agent-phase-resource-measurement.v1`
- `agent-phase-resource-measurement-validation.v1`
- `agent-cross-check-profile.v1`
- `agent-cross-check-profile-validation.v1`
- `agent-cross-check-receipt.v1`
- `agent-cross-check-receipt-validation.v1`

`agent-phase-resource-measurement.v1` reuses the usage-export envelope for
phase-level tokens, duration and resource counters. It rejects monetary phase
fields; USD-cost is not required for local or non-metered models.

`agent-cross-check-profile.v1` is disabled by default, token/resource-capped and
advisory unless a plan explicitly opts into blocking use.
