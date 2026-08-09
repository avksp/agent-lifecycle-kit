# Evidence plan

## Machine validation

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.host_protocol.test_usage_normalizers tests.model_routing.test_receipts tests.metrics.test_usage_export tests.adapters.test_host_local_usage_normalizers tests.adapters.test_gemini_cli_runner tests.adapters.test_kimi_code_runner tests.adapters.test_qwen_code_runner tests.live_hosts.test_adapter_module_loader tests.live_hosts.test_gemini_cli_harness tests.live_hosts.test_kimi_code_harness tests.live_hosts.test_qwen_code_harness tests.release.test_host_usage_normalizer_validator -q
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/release/validate_host_usage_normalizers.py --adapter-root adapters --evidence work/release-1-54/evidence/host-usage-normalizers.json
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/release/validate_no_model_calls.py --path src/agent_lifecycle/host_protocol/usage_normalizers.py --path src/agent_lifecycle/metrics/cost_collection.py --evidence work/release-1-54/evidence/no-model-calls.json
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/release/validate_docs_compat.py --evidence work/release-1-54/evidence/docs-compat.json
```

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover tests -q
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/release/validate_publication_versions.py --target-version 1.54.0 --target-ref v1.54.0 --evidence work/release-1-54/evidence/publication-versions.json
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/release/validate_publication_adoption.py --target-version 1.54.0 --evidence work/release-1-54/evidence/publication-adoption.json
```

## Evidence routes

The commands above are post-implementation gates. New test and validator paths
are produced by their owning workstreams before the commands run.

| Evidence ID | Producer route |
| --- | --- |
| `EV64-REUSE-CONTRACT` | `WS64-01, WS64-02` contract tests prove canonical sidecar reuse and operation/route/adapter/host/model/source binding without changing the host-operation schema. |
| `EV64-CORE-FALLBACK` | `WS64-01` metrics and receipt tests cover attested, estimated, missing and invalid usage, including rejection of `status: ATTESTED` when `source` is not `host`. |
| `EV64-REFERENCE-ADAPTERS` | `WS64-02` bounded fixtures and adapter normalizer validator. |
| `EV64-UNPROVEN-BOUNDARY` | `WS64-01, WS64-02` tests keep unsupported sources non-accepting. |
| `EV64-SECURITY` | `WS64-02, WS64-03` bounded secret/path fixtures and the adapter normalizer validator prove allowlist-only extraction and reject provider, network, process and dynamic-import code paths. |
| `EV64-DOCS` | `WS64-03` documentation compatibility validation. |
| `EV64-RELEASE-METADATA` | `WS64-03, WS64-04` update and validate package, plugin, marketplace and English/Russian exact package-pin surfaces. |
| `EV64-SINGLE-PARSER` | `WS64-01, WS64-02` descriptor, contained-loader, runner and live-harness tests prove one adapter-local parser per reference host and reject fixture-only declarations presented as qualified evidence. |

## Runtime boundaries

Fixture-only validation does not establish live host attestation. Each adapter
must remain `UNPROVEN` until its host-specific qualification records a redacted
live receipt. External parser inputs are bounded, local and redacted.

Evidence commands write to a release-specific directory after removing or
rejecting stale same-name receipts. Fixture artifacts can produce exact numeric
counters but must emit `source: fixture`, `status: ESTIMATED` and
`acceptedForS1S2: false`.
