# Goose 1.7.0 adapter evidence

Status: source-tree `EXPERIMENTAL`.

Tracked artifacts:

- Adapter descriptor: `adapters/goose/adapter.descriptor.json`.
- Capability manifest: `adapters/goose/capabilities.manifest.json`.
- Offline conformance baseline: `conformance/adapters/goose/offline-baseline.json`.
- Event stream fixture: `conformance/adapters/goose/event-stream-receipt.json`.
- Adapter docs: `docs/adapters/goose.md`.

Evidence summary:

- ACP is declared as a neutral host capability.
- Host probe is required before use.
- Unsupported operations remain fail-closed.
- No live host conformance, usage calibration, lifecycle proof, public
  directory approval or production promotion is claimed.

Promotion to `VERIFIED` requires accepted live host conformance, live usage
calibration, redacted evidence summary and lifecycle final proof for a concrete
Goose host range.
