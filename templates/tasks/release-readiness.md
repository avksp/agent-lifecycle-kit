# Release Readiness Task Template

Template status: DRAFT-ONLY.
Review gate: required.
Freeze gate: required.
Runtime defaults: none.

## Draft Inputs

- Release version: `{{release_version}}`
- Candidate branch: `{{candidate_branch}}`
- Required gates: `{{required_gates}}`
- Known risks: `{{known_risks}}`

## Draft Requirements

- Verify version, changelog and release inventory alignment.
- Run required test, docs and neutrality gates.
- Confirm adapter/support-matrix claims match evidence.
- Check for local paths, sensitive values and ignored artifacts in staged diff.
- Record residual risk before tag or release publication.

## Draft Evidence

- Release inventory evidence.
- Test matrix result.
- Docs compatibility result.
- Neutrality/security scan result.
- Tag and release verification.
