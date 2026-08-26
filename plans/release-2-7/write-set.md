# Write set

## WS27-01 - Review rounds and safe finding checks

- `src/agent_lifecycle/audit/implementation.py`
- `src/agent_lifecycle/contracts/implementation_audit_validation.py`
- `src/agent_lifecycle/contracts/review_round_schemas.py`
- `src/agent_lifecycle/contracts/finding_check_schemas.py`
- `src/agent_lifecycle/contracts/review_verdict.py`
- `src/agent_lifecycle/freeze/package_integrity.py`
- `src/agent_lifecycle/planning/manifest_contract.py`
- `src/agent_lifecycle/review/validation.py`
- `src/agent_lifecycle/review_mesh/results.py`
- `src/agent_lifecycle/review_mesh/synthesis.py`
- `src/agent_lifecycle/specification/completion_gate.py`
- `src/agent_lifecycle/workflow/finalization.py`
- `src/agent_lifecycle/workflow/reviews.py`
- `tests/audit/test_implementation_audit.py`
- `tests/audit/test_review_verdict.py`
- `tests/cli/test_plan_lock_commands.py`
- `tests/cli/test_review_mesh_commands.py`
- `tests/contracts/test_review_round_schemas.py`
- `tests/contracts/test_finding_check_schemas.py`
- `tests/contracts/test_review_verdict.py`
- `tests/freeze/test_plan_package_integrity.py`
- `tests/planning/test_manifest_contract.py`
- `tests/planning/test_sdd_services.py`
- `tests/review_mesh/test_quorum_gate.py`
- `tests/review_mesh/test_result_import.py`
- `tests/review_mesh/test_synthesis.py`
- `tests/specification/test_completion_gate.py`
- `tests/workflow/test_final_audit_outcomes.py`
- `tests/workflow/test_finalization.py`
- `tests/workflow/test_task_acceptance_audit_gate.py`

## WS27-02 - Statistical provenance, adequacy and metrics

- `src/agent_lifecycle/contracts/statistical_evidence_schemas.py`
- `src/agent_lifecycle/contracts/independent_evidence_schemas.py`
- `src/agent_lifecycle/contracts/audit_optimization_schemas.py`
- `src/agent_lifecycle/contracts/schemas.py`
- `src/agent_lifecycle/planning/completeness.py`
- `src/agent_lifecycle/metrics/audit_samples.py`
- `src/agent_lifecycle/metrics/audit_efficiency.py`
- `src/agent_lifecycle/metrics/audit_optimization.py`
- `src/agent_lifecycle/metrics/__init__.py`
- `tests/contracts/test_statistical_evidence_schemas.py`
- `tests/contracts/test_independent_evidence_schemas.py`
- `tests/planning/test_independence_requirements.py`
- `tests/metrics/fixtures/release-2-6-accounting-baseline.json`
- `tests/metrics/test_audit_samples.py`
- `tests/metrics/test_audit_efficiency.py`
- `tests/metrics/test_audit_optimization.py`

## WS27-03 - CLI, documentation and publication

- `src/agent_lifecycle/cli/metrics_parser.py`
- `src/agent_lifecycle/cli/dispatch_observability.py`
- `tests/cli/test_audit_efficiency_commands.py`
- `docs/reference/review-efficiency.md`
- `docs/ru/reference/review-efficiency.md`
- `docs/reference/evidence-independence.md`
- `docs/ru/reference/evidence-independence.md`
- `docs/reference/review-mesh.md`
- `docs/ru/reference/review-mesh.md`
- `docs/guides/install-and-first-run.md`
- `docs/ru/guides/install-and-first-run.md`
- `README.md`
- `docs/README.md`
- `docs/ru/README.md`
- `docs/reference/cli.md`
- `docs/ru/reference/cli.md`
- `CHANGELOG.md`
- `tasks/release-roadmap.md`
- `pyproject.toml`
- `uv.lock`
- `src/agent_lifecycle/_version.py`
- `.agents/plugins/marketplace.json`
- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `.cursor-plugin/plugin.json`
- `.cursor-plugin/marketplace.json`
- `adapters/claude/.claude-plugin/plugin.json`
- `adapters/codex/.codex-plugin/plugin.json`
- `adapters/cursor/.cursor-plugin/plugin.json`
- `tools/release/validate_docs_compat.py`
- `tests/release/test_docs_gates.py`
- `tools/release/publication_contract.py`
- `tests/release/test_publication_versions.py`
- `tests/release/test_publication_adoption.py`
