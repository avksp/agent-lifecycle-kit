# Baseline CI failure

## Remote evidence

- Pull request: `#155`
- Workflow: `python-quality`
- Run: `33123067521`
- Jobs: Python `3.11`, `3.12`, `3.13`, `3.14`
- Shared result: `FAIL`

The validator reported E501 findings in eight changed files and mypy findings
in seven changed files, with eleven unique affected source files. The exact
union from `work/release-2-7/quality/validation.json` is:

| Path | E501 | mypy |
| --- | --- | --- |
| `contracts/audit_optimization_schemas.py` | yes | no |
| `contracts/finding_check_schemas.py` | yes | no |
| `contracts/review_round_schemas.py` | no | yes |
| `contracts/review_verdict.py` | yes | no |
| `contracts/statistical_evidence_schemas.py` | no | yes |
| `metrics/audit_efficiency.py` | no | yes |
| `metrics/audit_optimization.py` | yes | yes |
| `metrics/audit_samples.py` | yes | yes |
| `review_mesh/results.py` | yes | yes |
| `review_mesh/synthesis.py` | yes | yes |
| `specification/completion_gate.py` | yes | no |

Every row is rooted at `src/agent_lifecycle/` and appears in `WS27Q-01`. No
other path occurs in the validation blocker list. Global mypy baseline entries
for unchanged files are not blockers for this corrective package and do not
justify broader authority. The current policy itself was not defective and
must not be edited by this package.

## Local reproduction

The exact producer and validator were replayed against Release 2.6 merge SHA
`30e2f2a55a2b8d959fa22b884e122952a2711ff7`. The producer completed, 1,993 tests
passed with one platform skip, and validation failed with the same blocker
classes as CI.

Local receipts are operator evidence under
`work/release-2-7/quality/`; they are not plan authority.
