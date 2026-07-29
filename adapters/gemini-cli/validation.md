# gemini-cli validation

Minimum offline checks before committing the projection:

```bash
agent-lifecycle adapter validate --descriptor adapters/gemini-cli/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/gemini-cli/adapter.descriptor.json --skip-host-commands
agent-lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
python tools/live_hosts/gemini_cli_harness.py --mode fixture-check --baseline conformance/core/adapter-baseline.v1.json --report <gemini-cli-fixture-check.json>
python tools/live_hosts/gemini_cli_harness.py --mode preflight --budget-mode subscription --max-invocations 1 --report <gemini-cli-preflight-report.json>
python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json --evidence <support-matrix-evidence.json>
```

These checks prove only an EXPERIMENTAL source projection and bounded harness
shape. Promotion to `VERIFIED` requires `--allow-live` live host conformance,
live calibration and lifecycle proof evidence bound to the tested host version.
