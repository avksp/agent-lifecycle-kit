# qwen-code 0.11.0 adapter evidence

Status: scaffold and inspection passed; support is `EXPERIMENTAL`.

Scope:

- Host: qwen-code `0.21.0`.
- Adapter descriptor: `adapters/qwen-code/adapter.descriptor.json`.
- Capability manifest: `adapters/qwen-code/capabilities.manifest.json`.
- Raw inspection report:
  `tasks/release-0-11/evidence/qwen-code/inspection/qwen-code-inspection-report.json`.

Safe inspection result:

- descriptor validation: `PASS`;
- scaffold projection files: `PASS`;
- `qwen --version`: `PASS`;
- `qwen --help`: `PASS`;
- `qwen extensions --help`: `PASS`;
- `qwen mcp --help`: `PASS`.

Discovered surfaces:

- headless execution supports `--prompt`;
- stream events are exposed through `--output-format stream-json`;
- model selection exposes `--model` and `--fallback-model`;
- permission behavior exposes `--safe-mode` and `--sandbox`, with ALK policy
  still fail-closed;
- resume/session, extensions and MCP command surfaces are present;
- usage attestation remains unproven until a live receipt is normalized and
  validated;
- bounded wall-time and tool-call caps were not discovered in the inspected
  root CLI help surface.

Non-promotion decision:

qwen-code is not promoted in this evidence note. No live host conformance
receipt, usage/calibration receipt, or lifecycle final proof has been accepted
for qwen-code.

Blocker classes: `BLOCKED_LIVE_HARNESS_NOT_IMPLEMENTED`,
`BLOCKED_NATIVE_RESOURCE_CAPS_NOT_DISCOVERED`.

Next action: implement a bounded qwen-code live harness that converts
`stream-json` output into portable host-operation receipts, proves usage
attestation, and enforces invocation, token and wall-clock caps before any
support-matrix promotion.
