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
