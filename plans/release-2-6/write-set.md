# Write set

## WS26-01 - Reviewed plan-lock CLI

- `src/agent_lifecycle/cli/planning_parsers.py`
- `src/agent_lifecycle/cli/dispatch_planning.py`
- `src/agent_lifecycle/cli/plan_lock_commands.py`
- `src/agent_lifecycle/freeze/package_integrity.py`
- `tests/cli/test_plan_lock_commands.py`
- `tests/freeze/test_locks.py`
- `tests/freeze/test_plan_package_integrity.py`

## WS26-02 - Phase resources, release accounting and provenance

- `src/agent_lifecycle/cli/metrics_parser.py`
- `src/agent_lifecycle/cli/dispatch_observability.py`
- `src/agent_lifecycle/contracts/release_accounting_schemas.py`
- `src/agent_lifecycle/contracts/metric_schemas.py`
- `src/agent_lifecycle/contracts/schemas.py`
- `src/agent_lifecycle/metrics/release_accounting.py`
- `src/agent_lifecycle/metrics/cost_collection.py`
- `src/agent_lifecycle/metrics/phase_resources.py`
- `src/agent_lifecycle/metrics/__init__.py`
- `tests/cli/test_phase_resource_commands.py`
- `tests/cli/test_release_accounting_commands.py`
- `tests/contracts/test_release_accounting_schemas.py`
- `tests/contracts/test_contracts.py`
- `tests/metrics/test_phase_resources.py`
- `tests/metrics/test_release_accounting.py`
- `tests/metrics/test_lifecycle_costs.py`

## WS26-03 - Session recipe, documentation and publication

- `docs/reference/release-accounting.md`
- `docs/ru/reference/release-accounting.md`
- `docs/guides/phase-session-handoff.md`
- `docs/ru/guides/phase-session-handoff.md`
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
- `tests/planning/test_continuity.py`
