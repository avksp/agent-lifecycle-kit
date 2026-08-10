# Grok Build Adapter

Grok Build is a host-specific `VERIFIED` ALK adapter projection for Grok Build
`0.2.117` on the tested host-local provider/model binding. This adapter is
`VERIFIED` for Grok Build `0.2.117`; live conformance exists and it does not
claim public approval. Its descriptor declares an ACP transport behind a
required local probe. The probe receipt does not start live model calls, and a
failed probe leaves the adapter fail-closed instead of silently falling back to
an unverified transport.

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
The adapter does not claim public directory approval, production platform
promotion, universal ACP support or verified OS sandbox containment.

## Planning-only launch status

Exact-version profile: `0.2.118`. Profile status: `UNSUPPORTED`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The CLI does not yet have a verified bounded stdin result transport for this contract.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter grok-build --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/grok-build.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/grok-build.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/grok-build.json
```

A successful version preflight does not authorize planning launch.
`managedLaunch.status` remains `WRAPPER_ONLY`, and adapter maturity cannot
promote planning support. See [Planning-only adapter
launch](../reference/planning-only-launch.md).
