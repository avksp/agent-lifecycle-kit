# Goose Adapter

The Goose adapter is a host-specific `VERIFIED` ALK adapter projection for
Goose `1.45.0` on the tested host-local provider/model binding.

## Files

- Descriptor: `adapters/goose/adapter.descriptor.json`
- Capability manifest: `adapters/goose/capabilities.manifest.json`
- Offline tests: `tests/adapters/goose/test_goose_adapter.py`
- Live harness: `tools/live_hosts/goose_harness.py`
- Shared JSON CLI loop: `tools/live_hosts/json_cli_harness.py`
- Probe and live harness tests: `tests/live_hosts/test_goose_adapter.py`

## Capability Contract

The descriptor declares `hostCapabilities[0].capabilityId = "acp"`. This is a
neutral capability claim, not a provider or model identity. Lifecycle semantics
remain delegated to ALK core, and unsupported operations use the shared
fail-closed policy.

The `VERIFIED` claim is limited to the tested host range and the redacted
live conformance evidence summary at
`docs/adapters/evidence/goose-live-verified.md`. The live harness uses bounded
`goose run` invocations with `--no-session`,
`--no-profile`, `--max-turns 1`, `--max-tool-repetitions 1`, explicit
host-local provider/model selection and post-invocation clean-worktree checks.

The verified scope covers Goose `1.45.0`, the tested host-local provider/model
binding and the evidence listed above.

## Validation

```bash
PYTHONPATH=src python3 -m agent_lifecycle adapter validate --descriptor adapters/goose/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
PYTHONPATH=src python3 -m pytest tests/adapters/goose tests/live_hosts/test_goose_adapter.py
```

## Planning-only launch status

Exact-version profile: `1.45.0`. Profile status: `CANDIDATE`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The no-profile/no-session stdin route forms
a static candidate; its qualification path is recorded in the planning guide.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter goose --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/goose.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/goose.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/goose.json
```

The planning route uses the status and evidence described in [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with Goose

The documented Goose route is the terminal command. An operator-owned wrapper
can expose the same ALK commands after review:

```bash
agent-lifecycle start --adapter goose --file task.md
```

The command creates ALK intake. For host execution, use the launch route through
a verified profile. See [Using ALK with an adapter](usage-modes.md).
