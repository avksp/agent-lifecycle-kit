# Evidence integrity

Evidence integrity is an optional, schema-backed proof layer for runs that must
show why a fix is correct, not only that the final audit passed. It is intended
for bug fixes, regressions, security defects, release blockers and other
high-risk changes.

The layer connects this chain:

```text
finding -> root cause -> fix impact -> regression evidence -> hash chain -> final proof
```

It is not enabled for ordinary tasks by default. A run opts in by setting
`proofIntegrityRequired: true`, by using a `proofIntegrityPolicy.mode` of
`required`, `bug-forensics` or `strict`, or by marking the final audit with
`proofIntegrityRequired: true`.

## Contracts

- `agent-proof-finding.v1`: stable finding identity. The generated
  `findingId` is derived from normalized rule/category/severity/path/symbol
  and message fields, so line-number or transient review-id changes do not
  create a new issue identity.
- `agent-root-cause-evidence.v1`: confirmed, rejected or inconclusive root
  cause evidence. Final proof integrity expects confirmed root causes for
  required findings.
- `agent-fix-impact-receipt.v1`: canonical fix-impact receipt. It lists
  changed files, related findings, root-cause digests, behavior changes,
  preserved behavior contracts, validation evidence and collateral-damage
  checks.
- `agent-receipt-hash-chain.v1`: append-only receipt chain. Each entry hashes
  artifact identity plus the previous entry hash.
- `agent-hash-chain-migration-policy.v1`: migration policy. New runs require a
  valid chain; legacy runs without one need an explicit exemption or backfill
  path.
- `agent-proof-integrity-receipt.v1`: final bundle that ties finding,
  root-cause, fix-impact, chain and migration evidence together.
- `agent-proof-integrity-validation.v1`: fail-closed validation result.

## Finalization

`workflow finalize` accepts an optional proof-integrity receipt:

```bash
agent-lifecycle workflow finalize \
  --state run.state.json \
  --operation-id finalize-op \
  --expected-revision 7 \
  --source-revision <sha> \
  --final-audit final/final-audit.json \
  --proof final/proof.json \
  --proof-integrity final/proof-integrity.json \
  --reason "accepted release evidence"
```

If proof integrity is required and `--proof-integrity` is missing, finalization
fails with `proof-integrity-receipt-missing`. If the receipt is present but
lineage, digests, required finding ids, required root-cause digests,
fix-impact digests or hash-chain links do not match, finalization fails with
`proof-integrity-validation-failed`.

When validation passes, final proof embeds the proof-integrity receipt identity
and validation result under `proofIntegrity`; workflow state records
`proofIntegrityReceipt`.

## Migration behavior

The default migration policy is `required-for-new-runs`:

- new runs must provide `agent-receipt-hash-chain.v1`;
- legacy runs may omit the chain only with a structured
  `legacyHashChainExemption`;
- backfill should be used when the original artifacts are still available;
- synthetic prose cannot replace missing receipt identity.

This keeps historical runs readable while making new proof evidence
append-only and digest-checked.
