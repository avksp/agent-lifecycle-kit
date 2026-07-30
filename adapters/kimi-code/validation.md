# Kimi Code validation

Minimum offline checks before committing the projection:

```bash
agent-lifecycle adapter validate --descriptor adapters/kimi-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/kimi-code/adapter.descriptor.json --skip-host-commands
agent-lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
python tools/live_hosts/kimi_code_harness.py --mode fixture-check --baseline conformance/core/adapter-baseline.v1.json --report <kimi-code-fixture-check.json>
python tools/live_hosts/kimi_code_harness.py --mode preflight --baseline conformance/core/adapter-baseline.v1.json --budget-mode subscription --max-invocations 1 --report <kimi-code-preflight-report.json>
python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json --evidence <support-matrix-evidence.json>
```

These checks prove only an EXPERIMENTAL source projection and bounded harness
shape. Promotion to `VERIFIED` requires bounded live host conformance, live
calibration, and lifecycle proof evidence bound to the tested host version.
