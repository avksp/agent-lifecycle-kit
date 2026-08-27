# Review efficiency

[Русская версия](../ru/reference/review-efficiency.md)

Review-efficiency evidence measures where audit time and tokens are spent
without lowering a review, security, architecture or quality gate. It is an
advisory accounting view, not a task-acceptance or optimization authority.

## Command

Build a report from an explicit `agent-audit-efficiency-input.v1` artifact:

```bash
agent-lifecycle metrics audit-efficiency \
  --input work/accounting/release-2-7.json \
  --comparison work/accounting/release-2-6.json \
  --out work/accounting/audit-efficiency.json
```

`--comparison` can be repeated. Every input is validated before the create-only
output is written. A malformed digest, invented value, invalid status or stale
comparison fails closed.

The command emits `agent-audit-efficiency-report.v1`. Its authority fields are
always `qualityFloorPreserved: true`, `advisoryOnly: true`, `autoApply: false`
and `productionPromotionClaimed: false`.

## Availability semantics

Each metric is one of `MEASURED`, `ESTIMATED`, `TIME_WINDOW_ONLY`, `MIXED` or
`UNAVAILABLE`. An unavailable metric has `value: null`; it is never converted
to zero. The four views remain separate:

- `alkProcess`;
- `implementation`;
- `audit`;
- `postAuditRemediation`.

Reports include confirmed and rejected findings, no-verdict sessions, audit
sessions and remediation events. Derived metrics include tokens and wall time
per confirmed finding, no-acceptance-effect share, rejected-finding share and
post-audit-remediation share.

## Comparisons

A single valid release returns `NO_COMPARISON`. It cannot produce a token or
wall-time reduction percentage. Comparisons require at least two lineage-bound
inputs with the same quality floor and complete comparable telemetry. Missing
implementation or controller telemetry remains `UNAVAILABLE` and blocks the
percentage instead of weakening the evidence requirement.

The tracked Release 2.6 fixture preserves the observed baseline: `29,195,208`
audit tokens, `9,278,567 ms` audit wall time and `12,228,901 ms` audit compute
time. Its non-audit token telemetry is `UNAVAILABLE`, not zero.

## Relationship to audit optimization

[Evidence-based audit optimization](audit-optimization.md) evaluates future
profiles and holdout tasks. Review efficiency explains measured cost and
outcomes. Neither route changes an active profile, frozen plan, task result or
review verdict automatically.

Statistical claims used by either route must satisfy
[evidence independence](evidence-independence.md). Review-round acceptance and
finding disposition remain governed by [Review Mesh](review-mesh.md).
