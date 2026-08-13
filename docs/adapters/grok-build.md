# Grok Build Adapter

Grok Build is a host-specific `VERIFIED` ALK adapter projection for Grok Build
`0.2.117` on the tested host-local provider/model binding. Its descriptor
declares an ACP transport behind a required local probe. The probe receipt
binds the transport to the verified host evidence.

Tracked source artifacts:

- `adapters/grok-build/adapter.descriptor.json`
- `adapters/grok-build/capabilities.manifest.json`
- `conformance/adapters/grok-build/offline-baseline.json`
- `conformance/adapters/grok-build/grok-acp-probe-negative-fixture.json`
- `conformance/adapters/grok-build/grok-acp-probe-positive-fixture.json`
- `docs/adapters/evidence/grok-build-live-verified.md`

The live conformance and calibration promotion is bounded to single-turn JSON
invocations with disabled subagents, memory and web search, plan permission
mode, an empty tools allowlist and clean-worktree checks after each host call.
The verified scope covers the host version, local provider/model binding and
ACP probe described in the evidence summary.

## Planning-only launch status

Exact-version profile: `0.2.118`. Profile status: `UNSUPPORTED`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The qualification path uses a bounded
stdin result transport and containment evidence.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter grok-build --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/grok-build.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/grok-build.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/grok-build.json
```

The planning route uses the status and evidence described in [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with Grok Build

The documented Grok Build route is the terminal command. A separately reviewed
host-local wrapper can expose the same ALK commands:

```bash
agent-lifecycle start --adapter grok-build --file task.md
```

The command creates ALK intake. For host execution, use the launch route through
a verified profile. See [Using ALK with an adapter](usage-modes.md).
