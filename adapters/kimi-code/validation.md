# kimi-code validation

Minimum offline checks before committing the projection:

```bash
agent-lifecycle adapter validate --descriptor adapters/kimi-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/kimi-code/adapter.descriptor.json --skip-host-commands
agent-lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json --evidence <support-matrix-evidence.json>
```

These checks prove only an EXPERIMENTAL source projection. Promotion to
`VERIFIED` requires bounded live host conformance, live calibration,
and lifecycle proof evidence bound to the tested host version.
