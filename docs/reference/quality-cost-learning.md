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

For repeated independent audits, use the more specific
[evidence-based audit optimization](audit-optimization.md) flow. It keeps
quality as the first gate, adds process-resource measurements and evaluates
candidate profiles on a bounded shared holdout set.

## Repeatable comparison

Use `agent-lifecycle benchmark evaluate` when a process change needs a fixed
quality baseline rather than historical aggregation. The bundled reference
suite applies deterministic oracles and reports false acceptances, retries,
elapsed time, and confidence-labeled token buckets. It remains read-only and
does not turn synthetic results into production evidence. See [Reference task
evaluation](reference-task-evaluation.md).

For repeated setup or environment comparisons, validate external execution
records with [execution-setup validation](benchmark-qualification.md) first. It requires
quality evidence and minimum task/stratum coverage before resource signals can
be compared; incomplete data returns `NO_RECOMMENDATION`.
