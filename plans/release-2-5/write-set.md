# Write set

## WS25-01 - Core contracts and validation

- `src/agent_lifecycle/contracts/external_job_schemas.py`
- `src/agent_lifecycle/contracts/schemas.py`
- `src/agent_lifecycle/host_protocol/external_jobs.py`
- `tests/contracts/test_external_job_schemas.py`
- `tests/host_protocol/test_external_jobs.py`

Keep `contracts/schemas.py` below the enforced 800-line target: new schema definitions belong in `external_job_schemas.py`; the shared registry receives only the import and schema-group registration.

## WS25-02 - Integration and bounded scenarios

- `src/agent_lifecycle/adapter_sessions/external_jobs.py`
- `src/agent_lifecycle/cli/adapter.py`
- `src/agent_lifecycle/cli/dispatch_adapters.py`
- `tests/adapter_sessions/test_external_jobs.py`
- `tests/adapter_sessions/test_external_job_cleanup.py`
- `tests/cli/test_external_job_commands.py`

`external_jobs.py` must compose the existing read-only `run_process` / `ProcessGroupOwner` boundary. `process.py`, `process_groups.py`, `test_process_cleanup.py` and `test_process_boundary_validator.py` are validation dependencies, not writable scope.

Persist mutable job state only in a private ignored adapter-owned root, defaulting to `.alk/external-jobs/<jobId>/attempt-<n>/`. Compose the existing canonical private-directory/private-file helpers and the session-store identity checks; do not reimplement a weaker path boundary. Each attempt has an immutable namespace; tests inject a temporary root. Portable lifecycle evidence stores only bounded metadata, digests and controlled locators.

`host_protocol/external_jobs.py` is receipt and protocol validation only. It must not import `adapter_sessions` or own mutable job state. Runtime composition, child cancellation and local persistence belong to `adapter_sessions/external_jobs.py`.

## WS25-03 - Activation evidence, bilingual documentation and publication

- `docs/reference/external-tool-jobs.md`
- `docs/ru/reference/external-tool-jobs.md`
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
