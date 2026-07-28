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
- `tools/release/validate_live_host_conformance.py` — fail-closed verifier for
  per-host lifecycle operation receipts. It validates each embedded host
  operation envelope through `HostOperationRequest` and `HostOperationReceipt`.

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

For a `VERIFIED` promotion gate, validate every promoted host explicitly:

```bash
python tools/release/validate_live_host_conformance.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --baseline conformance/core/adapter-baseline.v1.json \
  --receipt-dir <live-host-receipts-dir> \
  --promoted-hosts codex,claude-code \
  --evidence <live-host-conformance-evidence.json>

python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt-dir <live-calibration-receipts-dir> \
  --promoted-hosts codex,claude-code \
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

## Budget modes

Live harnesses support three budget modes before they start real host calls:

- `metered` requires an operator-approved `budgetCapUsd` and host-provided cost
  accounting.
- `subscription` does not require a USD cap, but it still requires
  `maxInvocations` and at least one resource cap: `maxBillableTokens` when the
  host exposes token accounting, or `maxWallSeconds` when token accounting is
  weak.
- `local` follows the same resource-cap rule as `subscription`; the cap protects
  local compute and runaway sessions rather than cloud spend.

The recommended minimum proof cap is derived from the release live calibration
profile: `13` required lifecycle operations plus `7` scenarios across `2`
cohorts with one run each, or `27` expected invocations. Add 20 percent headroom
and set `maxInvocations` to `33`. For the full recommended calibration, use five
runs per scenario/cohort: `83` expected invocations, capped at `100`.

When a cap is reached, the harness must stop before the next invocation and
write a blocking receipt. The operator or controller policy then decides whether
to continue on the same route, reroute to a cheaper/faster class, reroute to a
stronger class, split the task, or abort. Critical review phases must not be
silently downgraded.

## Receipt expectations

The receipt schema is `agent-lifecycle-live-calibration-receipt.v1`. A valid
receipt covers one host and must bind the profile digest, budget-target digest,
host, source revision, live invocation count and per-run usage metrics.

A universal `VERIFIED` claim requires one passing receipt per host listed in
`requiredHosts`. Single-receipt mode supports host-specific CI. Batch
promotion-gate mode requires one receipt file named `<host>.json` for each host
listed in `--promoted-hosts`.

The live host conformance receipt schema is
`agent-lifecycle-live-host-conformance-receipt.v1`. It must include one passing
operation record for every operation in `conformance/core/adapter-baseline.v1.json`,
must set `syntheticReplayUsed` to false, and must attest usage.

The verifier does not call models and does not infer billable usage from logs.
Host adapters or external CI must produce a signed receipt with usage already
attested by the relevant platform or measurement harness.
