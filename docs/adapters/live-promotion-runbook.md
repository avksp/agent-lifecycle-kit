# Adapter live-promotion runbook

This runbook promotes one host adapter from `EXPERIMENTAL` to host-specific
`VERIFIED`. It is host-neutral: each adapter supplies its own host commands,
but the evidence contract and release gates stay the same.

## Claim boundaries

- Source release: tagged repository contents plus offline checks. It does not
  prove public directory approval or broader production-promotion coverage.
- Host-specific `VERIFIED`: one named host version has bounded live host
  conformance, live calibration, and lifecycle proof evidence.
- Public directory approval: external marketplace review by the host owner. It
  is separate from source release and `VERIFIED` maturity.
- Production promotion: external signed CI, neutrality, live host, live
  calibration, and independent final-audit receipts. It is outside the offline
  source-release proof.

## Promotion phases

1. Preflight: record host CLI version, auth/session readiness, clean worktree
   status, invocation cap, token cap, and wall-clock cap.
2. Canary: run one bounded host invocation and verify usage attestation before
   spending the full promotion budget.
3. Capability bench: generate an adapter probe plan from the capability
   manifest and use it as drift coverage. The plan is declarative, starts no
   live calls, and cannot promote maturity by itself.
4. Conformance: produce a live host conformance receipt for every required
   adapter operation in `conformance/core/adapter-baseline.v1.json`.
5. Calibration: produce a live calibration receipt for every required scenario
   and cohort in `conformance/core/live-calibration-profile.v1.json`.
6. Lifecycle proof: run the Agent Lifecycle Kit workflow through task start,
   task result, task acceptance, final audit, and final proof.
7. Descriptor update: set only that adapter descriptor to `VERIFIED`, bind the
   tested host range, and list redacted evidence markers.
8. Docs update: update `docs/adapters/support-matrix.md`, adapter docs, and a
   committed redacted evidence summary. Raw local transcripts stay out of the
   source release unless intentionally summarized.
9. Final release proof: run release docs, support-matrix, candidate,
   neutrality, packaging, and CI checks before publishing the tag and GitHub
   Release object.

## Host secret handling

Use the host's normal credential source for model access. Some hosts use an
interactive login or credential store; API providers normally use environment
variables. For OpenInterpreter, custom providers declare the required
environment variable name through provider `env_key`; built-in providers use
their documented variable names.

ALK live harnesses may receive a private dotenv-style file through
`--host-env-file`, but no variable from that file is passed unless the operator
also supplies `--host-env-allow <NAME>`. This allowlist is intentionally
operator-provided: the harness must not infer allowed secrets from arbitrary
host output or persist the key value in receipts.

Reports and receipts may include only `agent-host-env-file-redacted.v1`
metadata: loaded variable names, counts, a path digest and `valuesRedacted:
true`. Run `validate_host_env_hygiene.py` with the same env file and allowlist
to prove the secret value is absent from emitted reports before accepting live
evidence.

## Required validators

Use these validators instead of prose-only review:

```bash
python tools/release/validate_adapter_conformance.py \
  --baseline conformance/core/adapter-baseline.v1.json \
  --host <adapter-id> \
  --evidence <adapter-conformance-evidence.json>

python tools/release/generate_adapter_probe_plan.py \
  --profile conformance/core/adapter-probe-profile.v1.json \
  --manifest adapters/<adapter-id>/capabilities.manifest.json \
  --out <adapter-probe-plan.json>

python tools/release/validate_adapter_probe_evidence.py \
  --plan <adapter-probe-plan.json> \
  --receipt-dir <live-host-receipts-dir> \
  --out <adapter-probe-evidence-validation.json>

python tools/release/validate_live_host_conformance.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --baseline conformance/core/adapter-baseline.v1.json \
  --receipt-dir <live-host-receipts-dir> \
  --promoted-hosts <host-id> \
  --probe-plan <adapter-probe-plan.json> \
  --evidence <live-host-conformance-evidence.json>

python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt-dir <live-calibration-receipts-dir> \
  --promoted-hosts <host-id> \
  --evidence <live-calibration-evidence.json>

python tools/release/validate_support_matrix.py \
  --support-matrix docs/adapters/support-matrix.md \
  --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json \
  --evidence <support-matrix-evidence.json>

python tools/release/validate_docs_compat.py \
  --evidence <docs-compat-evidence.json>

python tools/release/validate_host_env_hygiene.py \
  --report <host-harness-report-or-receipt.json> \
  --host-env-file <private-host-env-file> \
  --host-env-allow <PROVIDER_API_KEY_NAME> \
  --require-host-env-report \
  --evidence <host-env-hygiene-evidence.json>
```

## Fail-closed blockers

Promotion is blocked when any required receipt is missing, synthetic replay is
used as live evidence, usage is unattested, quality status is not `PASS`, a
budget ceiling is exceeded, the descriptor omits evidence markers, the support
matrix omits descriptor evidence, probe validation detects planned-operation
drift, or docs imply public directory approval or production-promotion coverage
that is not backed by external receipts.
