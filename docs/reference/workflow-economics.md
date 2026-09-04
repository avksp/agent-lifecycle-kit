# Workflow economics

Workflow economics compares explicit, immutable accounting fixtures without
granting authority to the comparison or its recommendation. It is intended to
show whether orchestration changes reduce measured cost while preserving the
same workload and an equal or stronger assurance floor.

## Compare fixtures

Use two fixtures that expose a stable workload identity, observed
implementation identity, gate outcomes and resource metrics:

```bash
agent-lifecycle metrics workflow-compare \
  --before tests/metrics/fixtures/release-2-8-continuation-baseline.json \
  --after tests/metrics/fixtures/release-2-10-continuation-baseline.json \
  --comparison-pair tests/metrics/fixtures/release-2-10-continuation-comparison-pair.json \
  --out work/workflow-comparison.json
```

The default comparison requires equal stable workload and implementation
identities. A source revision or version difference is comparable only when
both immutable fixtures carry the same canonical, predeclared before/after
pair and match its exact implementation tuples. A label supplied by the
caller, equal pair roles, a changed pair body, a late declaration or a digest
mismatch cannot establish comparability.

The result is `IMPROVED`, `REGRESSED`, `MIXED` or
`NO_COMPARABLE_BASELINE`. Metric deltas are meaningful only when their source
values are measured and all required gate outcomes remain equal or stronger.
Missing telemetry stays `UNAVAILABLE`; derived `MIXED` or `PARTIAL` aggregate
status is not source-value availability.

## Build a recommendation

```bash
agent-lifecycle metrics workflow-recommend \
  --comparison work/workflow-comparison.json \
  --task-shape release \
  --current-mode release \
  --required-mode release \
  --protected-work \
  --out work/workflow-recommendation.json
```

The recommendation is deterministic and advisory. It always keeps
`advisoryOnly: true`, `autoApply: false` and `authorityClaimed: false`; it
cannot mutate policy, workflow, acceptance or required gates. Protected
security, architecture, quality and release work cannot be downgraded from an
average or an apparent saving.

Both commands are local and create-only. They start no model, host process or
network call and do not rewrite predecessor fixtures.
