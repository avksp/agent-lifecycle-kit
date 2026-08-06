# Task Templates

These templates are draft-only starting points for ALK plans. They help an
operator shape a request, but they do not approve a plan, start execution or
replace review and freeze gates.

Template status: DRAFT-ONLY.
Review gate: required.
Freeze gate: required.
Runtime defaults: none.

Available templates:

- `bugfix`: reproduce, diagnose and repair a defect with optional Bug
  Forensics. Intake can recommend the profile, but the gate is advisory until
  review/freeze opt-in.
- `idea-to-pr`: turn an idea into a reviewed implementation plan.
- `pr-review`: review an existing change for correctness, scope and evidence.
- `merge-conflict-repair`: repair merge conflicts with minimal behavioral
  change.
- `release-readiness`: prepare a release candidate with evidence and residual
  risk.
- `research-plan`: research an area and stop with a reviewed plan, not code.
- `markdown-plan-review`: review one Markdown plan file or a folder import.
- `implementation-audit`: audit completed frozen-scope work against evidence.
- `cross-review`: coordinate optional independent reviewers without host
  auto-launch.
