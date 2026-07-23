# Live cost calibration

Live cost calibration is the production-promotion proof that the kit stays
within the declared usage and wall-time budgets on real host/model executions.

Synthetic replay files in `evals/synthetic/` are deterministic regression
fixtures only. They are useful for repeatable local checks, but they do not
prove token economy for Codex, Claude Code, Cursor, Hermes, OpenCode, or any
local model host.

## Contract files

- `conformance/core/live-calibration-profile.v1.json` — hosts eligible for
  live calibration, required scenarios/cohorts, usage metrics, receipt schema
  and synthetic replay policy.
- `conformance/core/budget-targets.v1.json` — absolute p95 targets and hard
  ceilings by SDD tier.
- `tools/release/validate_live_calibration.py` — fail-closed verifier that
  writes `agent-live-calibration-verification.v1` evidence.

The required scenario set includes both the 8k compact-context path and a
dedicated `S1-SMALL-CONTEXT-4K-STRICT-01` path for sub-8k local or constrained
hosts.

## Validation command

```bash
python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt <signed-live-calibration-receipt.json> \
  --evidence <live-calibration-evidence.json>
```

The command exits non-zero and writes blocking findings when:

- the live receipt is missing;
- the receipt uses synthetic replay data;
- usage metrics are missing, negative or unattested;
- the receipt host is not listed in the profile;
- a required scenario/cohort is missing for that host;
- `qualityStatus` is not `PASS` or `qualityRegressionCount` is non-zero;
- p95 usage exceeds a target or hard ceiling.

## Receipt expectations

The receipt schema is `agent-lifecycle-live-calibration-receipt.v1`. A valid
receipt covers one host and must bind the profile digest, budget-target digest,
host, source revision, live invocation count and per-run usage metrics.

A universal `VERIFIED` claim requires one passing receipt per host listed in
`requiredHosts`. The verifier intentionally validates one receipt at a time so
host-specific CI can publish independent evidence.

The verifier does not call models and does not infer billable usage from logs.
Host adapters or external CI must produce a signed receipt with usage already
attested by the relevant platform or measurement harness.
