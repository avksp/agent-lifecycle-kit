# Write set

## WS93-01 - Core contracts and validation

- `src/agent_lifecycle/contracts/security_analysis_schemas.py`
- `src/agent_lifecycle/contracts/bug_forensics_schemas.py`
- `src/agent_lifecycle/contracts/plan_manifest_schemas.py`
- `src/agent_lifecycle/contracts/schemas.py`
- `src/agent_lifecycle/quality/security_analysis.py`
- `src/agent_lifecycle/audit/security_analysis.py`
- `tests/contracts/test_security_analysis_schemas.py`
- `tests/contracts/test_bug_forensics_schemas.py`
- `tests/contracts/test_contracts.py`
- `tests/contracts/test_plan_manifest_schemas.py`
- `tests/quality/test_security_analysis.py`
- `tests/quality/test_bug_forensics_profile.py`
- `tests/quality/test_bug_forensics_recipes.py`

## WS93-02 - Integration and bounded scenarios

- `src/agent_lifecycle/quality/bug_forensics.py`
- `src/agent_lifecycle/workflow/bug_forensics_gates.py`
- `src/agent_lifecycle/workflow/implementation_audit_gate.py`
- `src/agent_lifecycle/workflow/plan_adoption.py`
- `src/agent_lifecycle/workflow/task_transitions.py`
- `src/agent_lifecycle/review_mesh/assignments.py`
- `src/agent_lifecycle/imports/security_findings.py`
- `src/agent_lifecycle/cli/parsers.py`
- `src/agent_lifecycle/cli/dispatch_contracts.py`
- `src/agent_lifecycle/cli/observability_parsers.py`
- `src/agent_lifecycle/cli/dispatch_observability.py`
- `tests/workflow/test_security_analysis_profile.py`
- `tests/workflow/test_bug_forensics_gates.py`
- `tests/workflow/test_plan_adoption.py`
- `tests/workflow/test_plan_adoption_runtime_contract.py`
- `tests/workflow/test_task_acceptance_audit_gate.py`
- `tests/review_mesh/test_assignments.py`
- `tests/review_mesh/test_independent_evidence.py`
- `tests/imports/test_security_findings.py`
- `tests/cli/test_security_analysis_commands.py`
- `tests/cli/test_quality_observability_commands.py`

## WS93-03 - Activation evidence, bilingual documentation and publication

- `docs/reference/security-analysis-profile.md`
- `docs/ru/reference/security-analysis-profile.md`
- `README.md`
- `docs/README.md`
- `docs/ru/README.md`
- `docs/reference/cli.md`
- `docs/ru/reference/cli.md`
- `docs/guides/install-and-first-run.md`
- `docs/ru/guides/install-and-first-run.md`
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
- `tests/conformance/test_synthetic_conformance.py`
- `fixtures/synthetic/s2-security-01.json`
- `conformance/fixtures.index.json`
