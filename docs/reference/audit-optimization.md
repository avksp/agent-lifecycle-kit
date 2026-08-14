# Evidence-based audit optimization

[Русская версия](../ru/reference/audit-optimization.md)

Evidence-based audit optimization helps tune repeated ALK reviews using local
execution evidence. It combines quality outcomes with waiting time, retries,
timeouts, token usage, CPU, memory and process counts. The result is a bounded
recommendation for future work; it does not change an active plan.

The flow is useful when the same kind of review is performed regularly, when a
team compares large and small or local models, or when an independent review
panel has become slow or expensive. For a single task without historical
evidence, use the ordinary lifecycle and collect receipts first.

## What is measured

The optimizer reads explicit local receipt bundles and keeps only a bounded
projection:

- task shape, phase, route class and request-shape digest;
- review status, finding counts, severities and independence status;
- success, blocker, correction, disagreement and false-acceptance outcomes;
- attempt, retry and timeout counts;
- attested input/output/billable tokens and wall time;
- attested CPU time, peak memory and process count.

It stores digests and counters, not prompts, transcripts, host output, secrets,
provider or model names, or absolute local paths. Missing host-local usage or
resource data is reported as unavailable and lowers confidence instead of being
invented.

## The operator flow

### 1. Build a local sample batch

Pass the explicit receipt bundles for completed reviews. The command does not
call a host or a model:

```bash
agent-lifecycle metrics audit-sample \
  --receipt work/review-01/receipt-bundle.json \
  --receipt work/review-02/receipt-bundle.json \
  --receipt work/review-03/receipt-bundle.json \
  --out work/audit-optimization/samples.json
```

Each input can contain the review, model-usage, process-execution and outcome
receipts for one operation. The output is an
`agent-audit-optimization-sample-batch.v1` artifact with a digest and explicit
privacy flags.

### 2. Describe a candidate profile

A candidate is a future profile, not a live mutation. It can be supplied as a
JSON file:

```json
{
  "profileId": "feature-review-balanced",
  "taskShape": "feature",
  "qualityFloor": "standard",
  "routeClass": "standard",
  "packetTokenLimit": 12000,
  "reviewerCountHint": 2,
  "timeoutSeconds": 900,
  "retryLimit": 1,
  "holdoutTasks": [
    {"taskId": "feature-01", "qualityPass": true, "billableTokens": 4200, "wallSeconds": 85},
    {"taskId": "feature-02", "qualityPass": true, "billableTokens": 3900, "wallSeconds": 78},
    {"taskId": "feature-03", "qualityPass": true, "billableTokens": 4500, "wallSeconds": 91}
  ]
}
```

The holdout set must contain at least three distinct tasks per shape and no
more than twelve tasks in the shared evaluation. A candidate is eligible only
when its measured quality reaches the requested floor and its false-acceptance
rate is zero. The same holdout pool is used for every candidate in a report.

### 3. Generate the report

```bash
agent-lifecycle metrics audit-report \
  --sample work/audit-optimization/samples.json \
  --candidate-profile profiles/feature-review-balanced.json \
  --task-shape feature \
  --quality-floor standard \
  --out work/audit-optimization/report.json \
  --terminal
```

The JSON artifact is `agent-audit-optimization-report.v1`. The terminal view
shows sample count, confidence, success and false-acceptance rates, correction
rate, p50/p95 time and token signals, the selected profile and the next action.
The report status is:

- `PASS`: enough evidence exists and a quality-safe candidate passed holdout
  evaluation;
- `NO_RECOMMENDATION`: more evidence is needed or every candidate misses a
  quality gate;
- `FAIL`: an input, evidence boundary or evaluation limit is invalid.

The optimizer blocks a recommendation when evidence is low-confidence, an
attestation set is mixed, a false acceptance or repeated remediation signal is
present, or a candidate would lower the required quality floor.

### 4. Record the decision

Create a proposal from the report. Without `--approved`, the artifact records a
pending decision:

```bash
agent-lifecycle metrics audit-proposal \
  --report work/audit-optimization/report.json \
  --target-kind project-profile \
  --target-revision feature-review-v2 \
  --out work/audit-optimization/proposal.json
```

After reviewing the report and its evidence, record explicit approval:

```bash
agent-lifecycle metrics audit-proposal \
  --report work/audit-optimization/report.json \
  --approved \
  --target-kind project-profile \
  --target-revision feature-review-v2 \
  --out work/audit-optimization/approved-proposal.json
```

Approval is advisory metadata. It does not edit the current project profile,
plan manifest or plan lock.

### 5. Write a new profile artifact

```bash
agent-lifecycle metrics audit-apply \
  --proposal work/audit-optimization/approved-proposal.json \
  --out work/audit-optimization/feature-review-v2.json
```

The output is a new `agent-audit-optimization-applied-profile.v1` artifact.
The previous profile remains the rollback point. A frozen plan can be followed
by a new plan revision, but its manifest and lock are never replaced by this
command.

## Choosing the right amount of evidence

Start with three completed, independently attested samples for a quick signal.
Treat `MEDIUM` confidence as a tuning hint and collect at least six samples for
the `HIGH` confidence path. Compare candidates on the same holdout tasks. Use
the smallest reviewer panel that meets the required quality floor; do not trade
away an S1/S2 gate to reduce time or tokens.

For large models, the report makes expensive packet or reviewer choices visible
and can identify excessive retries or long tail time. For small or local
models, compact packets and host-local token/resource receipts keep the same
quality checks while clearly marking unavailable measurements. The model and
provider remain selected by the adapter or host profile.

## Relationship to Review Mesh

Review Mesh creates assignments, imports redacted reviewer results and checks
an opted-in quorum. This optimizer observes the resulting receipts and helps
compare future profiles; it is not another reviewer, retry controller or quorum
authority. Review Mesh remains optional, and one model is a valid configuration
when the plan does not require independent dimensions.

## Related pages

- [Quality and cost learning](quality-cost-learning.md)
- [Multi-model review workflow](../guides/review-mesh-workflow.md)
- [Reference task evaluation](../guides/reference-task-evaluation.md)
- [Process execution observability](process-execution-observability.md)
