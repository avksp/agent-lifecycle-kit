# Write set

## Lead-owned

- `tasks/release-1-54/**`
- `work/release-1-54/**`

## WS64-01 Usage provenance contract and fallback

Owner: `usage-core-worker`.

Depends on: `none`.

Acceptance: `AC64-REUSE-CONTRACT, AC64-CORE-FALLBACK, AC64-UNPROVEN-BOUNDARY, AC64-SINGLE-PARSER`.

Writes:

- `src/agent_lifecycle/host_protocol/usage_normalizers.py`
- `src/agent_lifecycle/host_protocol/__init__.py`
- `src/agent_lifecycle/host_protocol/validation.py`
- `src/agent_lifecycle/model_routing/receipts.py`
- `src/agent_lifecycle/metrics/cost_collection.py`
- `src/agent_lifecycle/metrics/usage_export.py`
- `src/agent_lifecycle/contracts/schemas.py`
- `src/agent_lifecycle/contracts/compatibility.py`
- `tests/host_protocol/test_usage_normalizers.py`
- `tests/model_routing/test_receipts.py`
- `tests/metrics/test_usage_export.py`

## WS64-02 Reference adapter normalizers

Owner: `usage-adapter-worker`.

Depends on: `WS64-01`.

Acceptance: `AC64-REFERENCE-ADAPTERS, AC64-UNPROVEN-BOUNDARY, AC64-SECURITY, AC64-SINGLE-PARSER`.

Writes:

- `adapters/gemini-cli/usage_normalizer.py`
- `adapters/gemini-cli/runner.py`
- `adapters/gemini-cli/receipt_normalizer.py`
- `adapters/gemini-cli/adapter.descriptor.json`
- `adapters/gemini-cli/capabilities.manifest.json`
- `conformance/adapters/gemini-cli/event-stream-receipt.json`
- `adapters/kimi-code/usage_normalizer.py`
- `adapters/kimi-code/runner.py`
- `adapters/kimi-code/receipt_normalizer.py`
- `adapters/kimi-code/adapter.descriptor.json`
- `adapters/kimi-code/capabilities.manifest.json`
- `conformance/adapters/kimi-code/event-stream-receipt.json`
- `adapters/qwen-code/usage_normalizer.py`
- `adapters/qwen-code/runner.py`
- `adapters/qwen-code/receipt_normalizer.py`
- `adapters/qwen-code/adapter.descriptor.json`
- `adapters/qwen-code/capabilities.manifest.json`
- `conformance/adapters/qwen-code/event-stream-receipt.json`
- `tools/live_hosts/gemini_cli_harness.py`
- `tools/live_hosts/kimi_code_harness.py`
- `tools/live_hosts/qwen_code_harness.py`
- `tools/live_hosts/adapter_module_loader.py`
- `tests/adapters/test_host_local_usage_normalizers.py`
- `tests/adapters/test_gemini_cli_runner.py`
- `tests/adapters/test_kimi_code_runner.py`
- `tests/adapters/test_qwen_code_runner.py`
- `tests/live_hosts/test_gemini_cli_harness.py`
- `tests/live_hosts/test_kimi_code_harness.py`
- `tests/live_hosts/test_qwen_code_harness.py`
- `tests/live_hosts/test_adapter_module_loader.py`
- `tests/adapters/fixtures/host_usage/gemini-cli.json`
- `tests/adapters/fixtures/host_usage/kimi-code.json`
- `tests/adapters/fixtures/host_usage/qwen-code.json`
- `tests/adapters/fixtures/host_usage/redacted-secret.json`
- `tools/release/validate_host_usage_normalizers.py`
- `tests/release/test_host_usage_normalizer_validator.py`

## WS64-03 Support matrix and guides

Owner: `usage-docs-worker`.

Depends on: `WS64-02`.

Acceptance: `AC64-DOCS, AC64-SECURITY, AC64-RELEASE-METADATA`.

Writes:

- `README.md`
- `docs/README.md`
- `docs/ru/README.md`
- `docs/reference/host-local-token-accounting.md`
- `docs/ru/reference/host-local-token-accounting.md`
- `docs/reference/model-routing.md`
- `docs/ru/reference/model-routing.md`
- `docs/reference/usage-export.md`
- `docs/ru/reference/usage-export.md`
- `docs/adapters/support-matrix.md`
- `docs/ru/adapters/support-matrix.md`
- `docs/adapters/gemini-cli.md`
- `docs/ru/adapters/gemini-cli.md`
- `docs/adapters/kimi-code.md`
- `docs/ru/adapters/kimi-code.md`
- `docs/adapters/qwen-code.md`
- `docs/ru/adapters/qwen-code.md`
- `docs/guides/quickstart.md`
- `docs/ru/quickstart.md`
- `docs/reference/cli.md`
- `docs/ru/reference/cli.md`
- `docs/guides/production-resource-security.md`
- `docs/ru/guides/production-resource-security.md`
- `tools/release/validate_docs_compat.py`
- `tests/release/test_docs_gates.py`

## WS64-04 Release metadata

Owner: `release-metadata-worker`.

Depends on: `WS64-03`.

Acceptance: `AC64-RELEASE-METADATA`.

Writes:

- `CHANGELOG.md`
- `pyproject.toml`
- `uv.lock`
- `src/agent_lifecycle/_version.py`
- `.codex-plugin/plugin.json`
- `.agents/plugins/marketplace.json`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `.cursor-plugin/plugin.json`
- `.cursor-plugin/marketplace.json`
- `adapters/claude/.claude-plugin/plugin.json`
- `adapters/codex/.codex-plugin/plugin.json`
- `adapters/cursor/.cursor-plugin/plugin.json`
- `tests/adapters/test_publication_manifests.py`
- `tests/package/test_foundation.py`
- `tests/release/test_publication_versions.py`

## Parallel safety

Execution is strictly sequential: `WS64-01 -> WS64-02 -> WS64-03 -> WS64-04`.

This release owns common usage provenance. Release 1.57 may add qualified
Codex, Claude Code and OpenCode normalizers only through this contract.

The three reference live harnesses are owned here only to remove their parser
authority. They remain live-evidence tools and do not move into portable core.
