# Write set

## WS27Q-01: quality remediation

### Source

- `src/agent_lifecycle/contracts/audit_optimization_schemas.py`
- `src/agent_lifecycle/contracts/finding_check_schemas.py`
- `src/agent_lifecycle/contracts/review_round_schemas.py`
- `src/agent_lifecycle/contracts/review_verdict.py`
- `src/agent_lifecycle/contracts/statistical_evidence_schemas.py`
- `src/agent_lifecycle/metrics/audit_efficiency.py`
- `src/agent_lifecycle/metrics/audit_optimization.py`
- `src/agent_lifecycle/metrics/audit_samples.py`
- `src/agent_lifecycle/review_mesh/results.py`
- `src/agent_lifecycle/review_mesh/synthesis.py`
- `src/agent_lifecycle/specification/completion_gate.py`

### Existing regression tests

- `tests/contracts/test_finding_check_schemas.py`
- `tests/contracts/test_review_round_schemas.py`
- `tests/contracts/test_review_verdict.py`
- `tests/contracts/test_statistical_evidence_schemas.py`
- `tests/metrics/test_audit_efficiency.py`
- `tests/metrics/test_audit_optimization.py`
- `tests/metrics/test_audit_samples.py`
- `tests/review_mesh/test_result_import.py`
- `tests/review_mesh/test_synthesis.py`
- `tests/specification/test_completion_gate.py`

No other source, test, policy, baseline or publication file is writable. Test
paths are available only to add or tighten behavior-preservation coverage;
existing assertions and expected stable outputs may not be weakened.
