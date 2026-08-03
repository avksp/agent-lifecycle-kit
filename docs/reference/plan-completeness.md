# Plan completeness

Plan completeness is a structural pre-audit gate. It checks whether the chosen
SDD tier has the minimum authority needed to execute safely. It does not measure
prose length and does not replace independent plan review.

## Commands

```bash
agent-lifecycle plan completeness-check \
  --manifest tasks/release-x/plan.manifest.json \
  --profile profiles/plan-completeness-profile.v1.json \
  --out work/plan-completeness.json

agent-lifecycle plan check \
  --manifest tasks/release-x/plan.manifest.json \
  --require-completeness
```

`plan completeness-check` returns `agent-plan-completeness-validation.v1`. It
can return `status: FAIL` with actionable blockers while still printing JSON.
`plan check --require-completeness` is the enforcement path and raises
`plan-completeness-failed` when the selected tier is incomplete.

## Tier profiles

The default profile lives at `profiles/plan-completeness-profile.v1.json` and
uses `agent-plan-completeness-profile.v1`.

- `S0`: one bounded mechanical workstream, exact write scope and at least one
  validation command.
- `S1`: requirements, acceptance, evidence route, write ownership, validation
  and release-impact boundary.
- `S2`: requirements, acceptance, evidence route, write ownership, DAG,
  token/resource budget policy, context limits, security/release gates and
  final audit gates.

Typical blocker codes:

- `missing-evidence-route`
- `missing-write-ownership`
- `missing-budget-policy`
- `missing-context-limits`
- `missing-security-gate`
- `s2-final-audit-gate-missing`

## Small-model use

Small/local models should receive compact plans, but compact does not mean
underspecified. A small packet can omit narrative background when it still keeps
the active task, write scope, acceptance ids, evidence route, validation command
and output contract.
