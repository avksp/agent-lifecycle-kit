# Bug Forensics workflows

Use these recipes when the task is about a defect, regression, flaky failure,
incident or security bug. The advisor can suggest Bug Forensics from task text,
but the workflow gate stays off until a reviewed frozen plan opts in.

## Start from task intake

```bash
cat > work/bugs/checkout-regression.md <<'EOF'
# Task

Find and fix the checkout regression.

Known failing check:
pytest tests/checkout/test_totals.py::test_discount_total

Expected result:
- reproduce the failure before editing;
- identify a stable failure fingerprint;
- keep accepted and rejected hypotheses;
- prove the same fingerprint is green after the fix;
- record no collateral damage.
EOF

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/bugs/checkout-regression.md \
  --out work/bugs/checkout-intake.json
```

The receipt can include `bugForensicsAdvisory.recommendation: SUGGEST` and
`recommendedQualityProfiles: ["bug-forensics"]`. That is advice only. It does
not activate the workflow gate or start implementation.

## Defect search

Use this when the defect is suspected but not localized.

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --text "Investigate the failing checkout total test. Do not edit code until the failure is reproduced." \
  --out work/bugs/bug-search-intake.json
```

The plan should require:

- `agent-bug-reproduction-receipt.v1` before code edits;
- `agent-failure-fingerprint.v1` with stable failure fields;
- `agent-bug-hypothesis-ledger.v1` with rejected alternatives;
- `agent-regression-proof-receipt.v1` for red-to-green proof;
- `agent-fix-impact-receipt.v1` for behavior impact and collateral checks.

## Regression repair

Use this when a known behavior worked before and fails now.

```bash
agent-lifecycle report change-summary \
  --project-root . \
  --base origin/main \
  --out work/bugs/regression-change-summary.json
```

Bind the failing command, fingerprint and suspected diff range in the plan.
The fix is accepted only when the same fingerprint is red before the change and
green after the change.

## Flaky failures

Use this when a test sometimes passes and sometimes fails.

```bash
cat > work/bugs/flaky-task.md <<'EOF'
# Task

Investigate the flaky payment retry test.

Evidence to collect:
- repeated run count;
- failure count;
- whether a rerun passed;
- stable failure fingerprint if one exists.
EOF
```

The profile can attach flake signals to the gate receipt, but those signals do
not replace reproduction, fingerprint, hypothesis ledger, regression proof or
fix-impact evidence.

## Security bug

Use only synthetic task text and redacted evidence in portable docs. Do not
paste real secrets, exploit payloads or private incident details into task
files.

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --text "Investigate a security bug in request validation using redacted evidence only." \
  --out work/bugs/security-intake.json
```

For S2 or security-risk tasks, the Bug Forensics gate requires cross-check
evidence when the failure is classified as `security-bug` or `race`.

## Boundary

- Advisory output never enables blocking gates by itself.
- `qualityProfile: bug-forensics`, `qualityProfiles: ["bug-forensics"]` or
  `bugForensics.enabled: true` must be present in the reviewed task or frozen
  plan to activate the gate.
- The profile reuses existing receipts and does not introduce duplicate
  baseline proof, fingerprint or regression proof schemas.
