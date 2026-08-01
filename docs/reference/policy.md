# Lifecycle policy proposals

Policy proposals let ALK reduce avoidable lifecycle overhead only after the
recommendation data is strong enough and the required quality floor is still
preserved.

Build a read-only proposal:

```bash
agent-lifecycle policy tune --report <lifecycle-recommendation.json>
```

Apply only with explicit approval and an explicit output path:

```bash
agent-lifecycle policy tune \
  --report <lifecycle-recommendation.json> \
  --apply \
  --output <tuned-policy.json>
```

The command does not edit existing policy files. It writes a new
`agent-lifecycle-tuned-policy.v1` artifact with candidate changes, rollback
metadata, source proposal digest and preserved quality constraints.

Regression signals can block an apply:

```bash
agent-lifecycle policy tune \
  --report <lifecycle-recommendation.json> \
  --regression-signal <regression-signal.json>
```

Blocking signals include failed final audits, reopened work, rollback events
and repeated remediation. Low-confidence recommendations, no-op proposals and
protected downgrades also refuse apply with explicit reasons.

Protected work includes security-sensitive, release-sensitive, contract,
adapter, migration, architecture and S2 work. For those task classes, tuning
may keep or raise the lifecycle mode, but it cannot remove required evidence,
review or final proof.

Small local models should use `agent-lifecycle-policy-summary.v1` summaries for
the next action and refusal reasons. Larger models can inspect the full
proposal, regression signals and tuned policy artifact before approval.

## Runtime policy receipts

`agent-runtime-policy-receipt.v1` records an adapter policy decision without
turning advisory logging into a blocking claim. It supports `ALLOW`, `DENY`
and `ASK` decisions.

```bash
agent-lifecycle policy runtime-receipt \
  --policy-id <policy-id> \
  --action DENY \
  --subject <subject.json> \
  --adapter-evidence <adapter-evidence.json> \
  --enforcement-mode enforced \
  --out <runtime-policy-receipt.json>

agent-lifecycle policy runtime-check \
  --receipt <runtime-policy-receipt.json>
```

`enforcementMode: enforced` passes only when adapter evidence proves
pre-execution enforcement and the decision was recorded before execution.
Adapters that can only log after the fact must use `enforcementMode:
advisory`; the receipt remains useful evidence, but it is not a blocking
policy gate.
