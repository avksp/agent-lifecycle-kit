# Adapter live-promotion runbook

This runbook promotes one host adapter from `EXPERIMENTAL` to host-specific
`VERIFIED`. It is host-neutral: each adapter supplies its own host commands,
but the evidence contract and release gates stay the same.

## Claim Boundaries

- Source release: tagged repository contents plus offline checks. It does not
  prove public directory approval or broader production-promotion coverage.
- Host-specific `VERIFIED`: one named host version has bounded live host
  conformance, live calibration, and lifecycle proof evidence.
- Public directory approval: external marketplace review by the host owner. It
  is separate from source release and `VERIFIED` maturity.
- Production promotion: external signed CI, neutrality, live host, live
  calibration, and independent final-audit receipts. It is outside the offline
  source-release proof.

## Promotion Phases

1. Preflight: record host CLI version, auth/session readiness, clean worktree
   status, invocation cap, token cap, and wall-clock cap.
2. Canary: run one bounded host invocation and verify usage attestation before
   spending the full promotion budget.
3. Conformance: produce a live host conformance receipt for every required
   adapter operation in `conformance/core/adapter-baseline.v1.json`.
4. Calibration: produce a live calibration receipt for every required scenario
   and cohort in `conformance/core/live-calibration-profile.v1.json`.
5. Lifecycle proof: run the Agent Lifecycle Kit workflow through task start,
   task result, task acceptance, final audit, and final proof.
6. Descriptor update: set only that adapter descriptor to `VERIFIED`, bind the
   tested host range, and list redacted evidence markers.
7. Docs update: update `docs/adapters/support-matrix.md`, adapter docs, and a
   committed redacted evidence summary. Raw local transcripts stay out of the
   source release unless intentionally summarized.
8. Final release proof: run release docs, support-matrix, candidate,
   neutrality, packaging, and CI checks before publishing the tag and GitHub
   Release object.

## Required Validators

Use these validators instead of prose-only review:

```bash
python tools/release/validate_adapter_conformance.py \
  --baseline conformance/core/adapter-baseline.v1.json \
  --host <adapter-id> \
  --evidence <adapter-conformance-evidence.json>

python tools/release/validate_live_host_conformance.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --baseline conformance/core/adapter-baseline.v1.json \
  --receipt-dir <live-host-receipts-dir> \
  --promoted-hosts <host-id> \
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
```

## Fail-Closed Blockers

Promotion is blocked when any required receipt is missing, synthetic replay is
used as live evidence, usage is unattested, quality status is not `PASS`, a
budget ceiling is exceeded, the descriptor omits evidence markers, the support
matrix omits descriptor evidence, or docs imply public directory approval or
production-promotion coverage that is not backed by external receipts.
