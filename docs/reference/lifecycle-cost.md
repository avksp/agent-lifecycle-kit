# Lifecycle cost accounting

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

Generate a report from explicit JSON artifacts with:

```bash
agent-lifecycle metrics cost-report \
  --mode standard \
  --artifact <usage-receipt.json> \
  --artifact <task-review.json> \
  --out <lifecycle-cost-report.json> \
  --summary-out <compact-cost-summary.json>
```

`cost-report` is read-only for source artifacts and host state. It writes only
the requested output files, then validates the generated report with the same
`cost-check` rules. The generated report records `sourceArtifacts`, `lineage`,
`usageConfidence`, and `compactSummary`.

Usage confidence is explicit:

- `ATTESTED`: a host or lifecycle receipt supplied billable usage.
- `ESTIMATED`: ALK estimated local or tooling work from existing artifacts.
- `MISSING`: an artifact requires usage data but does not contain usable
  counters.

The compact summary uses `agent-lifecycle-cost-summary.v1` and also carries the
standard compact-context fields, so it can be passed directly to
`agent-lifecycle context check`.

Build an advisory mode recommendation from accumulated reports with:

```bash
agent-lifecycle metrics recommend \
  --report <first-cost-report.json> \
  --report <second-cost-report.json> \
  --task-shape feature \
  --current-mode standard \
  --out <lifecycle-recommendation.json> \
  --summary-out <compact-recommendation-summary.json>
```

Recommendations are advisory only. They never change policy automatically and
must preserve the configured quality floor for the task shape, SDD tier and
risk flags. Missing or weak statistics keep confidence low and favor the
current or minimum safe mode.

When a recommendation is stable, `agent-lifecycle policy tune` can turn it into
an explicit policy proposal:

```bash
agent-lifecycle policy tune --report <lifecycle-recommendation.json>
```

The default command path is read-only. Writing a policy artifact requires both
`--apply` and `--output`, and the output carries before/after values, rollback
metadata, regression-signal status and preserved quality constraints.

Modes are `light`, `standard`, `strict` and `release`. Each mode has default
limits for pipeline token share, pipeline step share, pipeline tokens and
pipeline steps. If strict or release work intentionally exceeds the default
pipeline limits, the report needs `overLimitReason`.

Small local models can use the compact validation receipt to decide whether the
process is still helping the task and which mode is reasonable next. Larger
models can inspect the full generated report, source artifact digests,
underlying tests, reviews and final proof without losing quality.
