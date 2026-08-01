# OpenInterpreter 1.13.0 adapter evidence

Status: superseded source-tree `EXPERIMENTAL` snapshot.

This historical snapshot is retained for the release 1.13 adapter introduction.
The current source-tree claim is host-specific `VERIFIED` in
`docs/adapters/evidence/openinterpreter-live-verified.md`.

Tracked artifacts:

- Adapter descriptor: `adapters/openinterpreter/adapter.descriptor.json`.
- Capability manifest: `adapters/openinterpreter/capabilities.manifest.json`.
- Offline conformance baseline: `conformance/adapters/openinterpreter/offline-baseline.json`.
- Event stream fixture: `conformance/adapters/openinterpreter/event-stream-receipt.json`.
- Adapter docs: `docs/adapters/openinterpreter.md`.

Evidence summary:

- The adapter is a host-local compatible CLI projection.
- A bounded JSONL harness exists for `interpreter exec` and delegates receipts,
  validation loops, budget checks and diagnostics to the shared live-host
  harness module.
- Lifecycle semantics remain delegated to ALK core.
- Local preflight for `interpreter 0.0.34` is blocked because the selected
  provider credential variable is not visible to the `interpreter` process.
  Provider-flexible setups use their own configured or documented credential
  variable names.
- The live harness supports operator-scoped env injection through
  `--host-env-file` plus explicit `--host-env-allow`; emitted reports contain
  only redacted host-env metadata.
- No live host conformance, usage calibration, lifecycle proof, public
  directory approval or production promotion is claimed.

Local blocked preflight artifacts:

- `work/release-1-18/evidence/preflight/openinterpreter-preflight-report.json`
  (`sha256:c75b45210ffd205a99b6c37df56a9f21992e7655de2fcbe685b9f7c0247d0b95`).
- `work/release-1-18/evidence/openinterpreter-containment-receipt.json`
  (`sha256:a121c6ec0d8768634ef740f45a5b3afe9ca2a271163827702b55584d1cf6b9f3`).

Promotion to `VERIFIED` requires accepted live host conformance, live usage
calibration, redacted evidence summary and lifecycle final proof for a concrete
OpenInterpreter host range.
