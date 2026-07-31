# Grok Build 1.13.0 adapter evidence

Status: source-tree `EXPERIMENTAL`.

Tracked artifacts:

- Adapter descriptor: `adapters/grok-build/adapter.descriptor.json`.
- Capability manifest: `adapters/grok-build/capabilities.manifest.json`.
- Offline conformance baseline: `conformance/adapters/grok-build/offline-baseline.json`.
- Negative ACP probe fixture: `conformance/adapters/grok-build/grok-acp-probe-negative-fixture.json`.
- Adapter docs: `docs/adapters/grok-build.md`.

Evidence summary:

- ACP use is probe-gated.
- Negative probe evidence is recorded as fail-closed.
- No live host conformance, usage calibration, lifecycle proof, public
  directory approval or production promotion is claimed.

Promotion to `VERIFIED` requires accepted live host conformance, live usage
calibration, redacted evidence summary and lifecycle final proof for a concrete
Grok Build host range.
