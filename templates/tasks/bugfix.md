# Bugfix Task Template

Template status: DRAFT-ONLY.
Review gate: required.
Freeze gate: required.
Runtime defaults: none.

Quality profile: bug-forensics optional when the task explicitly asks to find
or fix a bug.

## Draft Inputs

- Symptom: `{{bug_summary}}`
- Reproduction command or failing check: `{{failing_command}}`
- Expected behavior: `{{expected_behavior}}`
- Observed behavior: `{{observed_behavior}}`
- Suspect area: `{{suspect_scope}}`

## Draft Requirements

- Reproduce the failure before editing code.
- Record a stable failure fingerprint.
- Keep a hypothesis ledger with accepted and rejected causes.
- Apply the smallest fix that satisfies the root cause.
- Prove the same failing case is green after the fix.
- Run neighboring checks and record no collateral damage.

## Draft Evidence

- Bug reproduction receipt.
- Failure fingerprint.
- Hypothesis ledger.
- Regression proof receipt.
- Fix impact receipt.
