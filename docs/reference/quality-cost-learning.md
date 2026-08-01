# Quality-cost learning

Quality-cost learning is a local, advisory feedback loop over explicit ALK
receipts. It helps choose the fastest sufficient lifecycle path for similar
future tasks while preserving quality floors.

It does not call provider APIs, upload telemetry, train a model, require USD
cost fields, or build provider/model leaderboards in core.

## Flow

```bash
agent-lifecycle metrics outcome-index \
  --artifact <task-result.json> \
  --artifact <completion-gate.json> \
  --out <outcome-index.json>

agent-lifecycle metrics quality-signals \
  --index <outcome-index.json> \
  --out <quality-cost-signals.json>

agent-lifecycle metrics learn-recommend \
  --signals <quality-cost-signals.json> \
  --task-shape small-fix \
  --current-mode strict \
  --out <recommendation.json> \
  --summary-out <recommendation-summary.json>
```

`agent-task-outcome-index.v1` groups local receipts by task shape, lifecycle
mode, route class and profile. `agent-quality-cost-signals.v1` reports success
rate, blocker rate, retries, remediation loops, tokens, wall time and tool
calls. `agent-lifecycle-recommendation.v1` remains advisory with
`autoApply: false`, confidence, evidence digests, rollback metadata and
`qualityFloorPreserved: true`.

Low-confidence data keeps the current or floor mode. Any policy change must go
through the explicit policy proposal/apply path.
