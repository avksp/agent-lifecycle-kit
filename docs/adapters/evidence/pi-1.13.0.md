# Pi 1.13.0 adapter evidence

Status: source-tree `EXPERIMENTAL`.

Tracked artifacts:

- Adapter descriptor: `adapters/pi/adapter.descriptor.json`.
- Capability manifest: `adapters/pi/capabilities.manifest.json`.
- Offline conformance baseline: `conformance/adapters/pi/offline-baseline.json`.
- Event stream fixture: `conformance/adapters/pi/event-stream-receipt.json`.
- Adapter docs: `docs/adapters/pi.md`.

Evidence summary:

- The adapter is represented as RPC/JSON plus AGENTS/agentskills projection.
- Lifecycle semantics remain delegated to ALK core.
- No live host conformance, usage calibration, lifecycle proof, public
  directory approval or production promotion is claimed.

Promotion to `VERIFIED` requires accepted live host conformance, live usage
calibration, redacted evidence summary and lifecycle final proof for a concrete
Pi host range.
