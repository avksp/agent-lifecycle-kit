# Kimi Code 0.12.0 adapter evidence

Status: scaffold and inspection passed; support is `EXPERIMENTAL`.

Scope:

- Host: Kimi Code `0.30.0` through local `kimi` CLI.
- Adapter descriptor: `adapters/kimi-code/adapter.descriptor.json`.
- Capability manifest: `adapters/kimi-code/capabilities.manifest.json`.
- Raw inspection report:
  `tasks/release-0-12/evidence/kimi-code/inspection/kimi-code-inspection-report.json`.

Safe inspection result:

- descriptor validation: `PASS`;
- scaffold projection files: `PASS`;
- `kimi --version`: `PASS`;
- `kimi --help`: `PASS`;
- `kimi provider --help`: `PASS`;
- `kimi export --help`: `PASS`;
- `kimi acp --help`: `PASS`;
- `kimi doctor --help`: `PASS`.

Discovered surfaces:

- headless execution supports `--prompt`;
- stream events are exposed through `--output-format stream-json`;
- model selection exposes `--model`;
- permission behavior exposes `--yolo`, `--auto` and `--plan`, with ALK policy
  still fail-closed;
- skills directory selection, provider discovery, session export, ACP stdio
  server discovery and configuration validation command surfaces are present;
- usage attestation remains unproven until a live receipt is normalized and
  validated.

Non-promotion decision:

Kimi Code is not promoted in this evidence note. No live host conformance
receipt, usage/calibration receipt, or lifecycle final proof has been accepted
for Kimi Code.

Blocker class: `BLOCKED_LIVE_HARNESS_NOT_IMPLEMENTED`.

Next action: implement a bounded Kimi Code live harness that converts
`stream-json` output into portable host-operation receipts, proves usage
attestation, and enforces invocation, token and wall-clock caps before any
support-matrix promotion.
