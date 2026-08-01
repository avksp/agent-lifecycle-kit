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
