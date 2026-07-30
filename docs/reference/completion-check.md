# Completion check

`completionCheck` is an optional specification field for outcomes that need an
observable finish signal beyond task acceptance and final audit prose.

When present, the workflow copies it into runtime state during plan adoption.
`workflow finalize` then fails closed until the configured
`agent-completion-check-receipt.v1` exists, has `status: PASS`, matches the
same run, package, plan revision, plan digest and source revision, and includes
all required evidence ids.

Minimal specification fragment:

```json
{
  "completionCheck": {
    "schemaVersion": "agent-completion-check.v1",
    "checkId": "final-user-outcome",
    "kind": "verification",
    "description": "The requested outcome is demonstrated by the final evidence.",
    "receiptPath": "final/completion-check-receipt.json",
    "requiredEvidenceIds": ["EV-FINAL"]
  }
}
```

For operator-owned decisions, set `kind` to `external-action`. The receipt must
then bind the `externalActionReceipt` identity created from the existing
`agent-external-action-receipt.v1` workflow resume transition. This keeps human
decisions in the existing lifecycle state instead of creating a parallel
approval path.
