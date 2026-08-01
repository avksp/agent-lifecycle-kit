# Merge Conflict Repair Task Template

Template status: DRAFT-ONLY.
Review gate: required.
Freeze gate: required.
Runtime defaults: none.

## Draft Inputs

- Source branch: `{{source_branch}}`
- Target branch: `{{target_branch}}`
- Conflict files: `{{conflict_files}}`
- Behavior that must be preserved: `{{preserved_behavior}}`

## Draft Requirements

- Inspect both sides of every conflict before editing.
- Preserve intended behavior from both branches where compatible.
- Keep conflict repair scoped to merge resolution.
- Run targeted validation for every touched area.
- Record any behavior that could not be preserved.

## Draft Evidence

- Conflict file list.
- Resolution rationale.
- Focused validation commands.
- Residual conflict or behavior-risk note.
