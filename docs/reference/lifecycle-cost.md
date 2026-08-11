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

Currency fields are never required for local or subscription models. When a
metered host wants an early operator prompt, `meteredAskThreshold` belongs in
the metered budget policy only and remains advisory; hard caps still decide
whether execution must pause.

Adaptive lifecycle policy uses the same resource discipline. It may accept
host-reported monetary metadata only for `budgetMode: "metered"`, but mode
selection uses tokens, wall time, invocations, retries and quality floors, not
live currency lookup.

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

Quality-cost learning can use local lifecycle receipts directly:

```bash
agent-lifecycle metrics outcome-index --artifact <task-result.json> --out <outcome-index.json>
agent-lifecycle metrics quality-signals --index <outcome-index.json> --out <signals.json>
agent-lifecycle metrics learn-recommend --signals <signals.json> --task-shape feature
```

This path reports `agent-task-outcome-index.v1` and
`agent-quality-cost-signals.v1`. It uses tokens, wall time, tool calls, retries,
remediation loops and blocker rate. It does not require USD fields or live
telemetry.

For per-task neutral inputs, build an adaptive decision with:

```bash
agent-lifecycle policy adaptive-decision \
  --request <adaptive-request.json> \
  --baseline-profile profiles/lifecycle-baselines.v1.json \
  --out <adaptive-decision.json>
```

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

The validator currently applies those ratios to `pipelineCompliance` only.
`coordination` is reported as a separate category and is not included in the
pipeline share. A passing receipt therefore proves compliance with the declared
pipeline limits, but it does not by itself prove that all process overhead is
less than half of a real run. That conclusion requires complete phase data from
the host and inspection of both categories. For light and standard work, a
dominant combined process share is a signal to remove duplicate checks, reduce
optional review, split the task or avoid ALK for that task.

Small local models can use the compact validation receipt to decide whether the
process is still helping the task and which mode is reasonable next. Larger
models can inspect the full generated report, source artifact digests,
underlying tests, reviews and final proof without losing quality.
