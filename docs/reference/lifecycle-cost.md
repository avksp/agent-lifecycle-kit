# Lifecycle Cost Accounting

Lifecycle cost accounting separates work that solves the user task from work
that proves the lifecycle was followed. This keeps ALK useful instead of
letting process checks consume the run unnoticed.

`agent-lifecycle-cost-report.v1` entries use four categories:

- `implementation`: code, docs or artifacts that directly solve the task;
- `productValidation`: tests and review that validate changed behavior;
- `pipelineCompliance`: planning, freeze, acceptance checks, ownership checks,
  lifecycle review and final proof mechanics;
- `coordination`: routing, handoff and status work that is not direct
  implementation.

```json
{
  "schemaVersion": "agent-lifecycle-cost-report.v1",
  "mode": "standard",
  "entries": [
    {"category": "implementation", "tokens": 9000, "steps": 4},
    {"category": "productValidation", "tokens": 2500, "steps": 2},
    {"category": "pipelineCompliance", "tokens": 2400, "steps": 3},
    {"category": "coordination", "tokens": 500, "steps": 1}
  ],
  "productionPromotionClaimed": false
}
```

Validate the report with:

```bash
agent-lifecycle metrics cost-check --receipt <lifecycle-cost-report.json>
```

Modes are `light`, `standard`, `strict` and `release`. Each mode has default
limits for pipeline token share, pipeline step share, pipeline tokens and
pipeline steps. If strict or release work intentionally exceeds the default
pipeline limits, the report needs `overLimitReason`.

Small local models can use the compact validation receipt to decide whether the
process is still helping the task. Larger models can inspect the full report,
underlying tests, reviews and final proof without losing quality.
