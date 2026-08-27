# Acceptance criteria

| ID | Requirement | Evidence | Deterministic acceptance |
| --- | --- | --- | --- |
| `AC27Q-QUALITY` | `R27Q-QUALITY` | `EV27Q-QUALITY` | The exact `run_python_quality.py` and `validate_python_quality.py` commands, using policy `policy/python-quality.json` and base SHA `30e2f2a55a2b8d959fa22b884e122952a2711ff7`, both emit `PASS`; validation contains zero blockers and no new or changed-path finding. |
| `AC27Q-BEHAVIOR` | `R27Q-BEHAVIOR` | `EV27Q-BEHAVIOR` | Focused tests for every affected domain and the complete unittest suite pass. Existing canonical fixture outputs and stable error codes remain unchanged. |
| `AC27Q-BOUNDARY` | `R27Q-BOUNDARY` | `EV27Q-BOUNDARY` | The implementation diff is limited to declared source/test paths and consists only of expression wrapping plus explicit type narrowing for invariants already checked at runtime. No policy, baseline, schema meaning, authority, threshold or publication metadata changes. |
| `AC27Q-REGRESSION` | `R27Q-REGRESSION` | `EV27Q-REGRESSION` | Module/package dependency gates, architecture complexity, neutrality and all four remote `python-quality` jobs pass on the final candidate. |
