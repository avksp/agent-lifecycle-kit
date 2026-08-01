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

## Completion gate

`agent-completion-gate-receipt.v1` is an optional deterministic decision over
current lifecycle evidence. It answers whether the task should `STOP`,
`CONTINUE`, `ESCALATE`, `SPLIT` or become `FOLLOW_UP` work.

```bash
agent-lifecycle specification completion-gate \
  --state <run.state.json> \
  --final-audit <final-audit.json> \
  --input <completion-gate-input.json> \
  --out <completion-gate.json>
```

`STOP` and `FOLLOW_UP` require accepted required tasks, passing required
validation, no open workflow blockers, no finalization-blocking follow-ups and
ready final audit evidence. `CONTINUE`, `ESCALATE` and `SPLIT` carry
deterministic reason codes so the next action is explicit.

`workflow finalize` can bind the receipt with
`--completion-gate-receipt <completion-gate.json>`. When bound, finalization
fails closed unless the receipt allows finalization and its input digests match
the current state, final audit and optional follow-up register.
