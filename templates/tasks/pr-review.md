# PR Review Task Template

Template status: DRAFT-ONLY.
Review gate: required.
Freeze gate: required.
Runtime defaults: none.

## Draft Inputs

- PR or branch: `{{change_ref}}`
- Base branch: `{{base_ref}}`
- Requested focus: `{{review_focus}}`
- Required checks: `{{required_checks}}`

## Draft Requirements

- Compare the change against the base.
- Lead with correctness, regression, security and evidence findings.
- Distinguish blocking issues from residual risk.
- Verify tests and docs match the behavior being changed.
- Avoid proposing unrelated refactors.

## Draft Evidence

- Diff summary.
- Finding list with file references.
- Check results.
- Merge readiness verdict.
