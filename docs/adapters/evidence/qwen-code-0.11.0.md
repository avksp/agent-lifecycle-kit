# qwen-code 0.11.0 adapter evidence

Status: historical scaffold and inspection checkpoint; support was
`EXPERIMENTAL` at this checkpoint.

Superseded by:

- `docs/adapters/evidence/qwen-code-glm52-live-2026-07-29.md`.
- qwen-code `0.21.0` is now host-specific `VERIFIED` in the current source tree
  after live conformance, live calibration, and ALK lifecycle proof passed.

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

2026-07-29 GLM 5.2 smoke:

- `qwen --model glm-5.2 --safe-mode --output-format stream-json` returned
  `PASS` with model `GLM-5.2`;
- host usage fields were present in the stream result:
  `input_tokens=13476`, `output_tokens=15`, `total_tokens=13491`;
- redacted summary:
  `tasks/release-0-11/evidence/qwen-code/glm52-smoke/qwen-glm52-smoke-summary.json`;
- this was a bounded model smoke only, not a live host conformance receipt,
  live calibration receipt, adapter runner proof, or ALK lifecycle final proof.

Historical non-promotion decision:

qwen-code is not promoted in this evidence note. No live host conformance
receipt, usage/calibration receipt, or lifecycle final proof has been accepted
for qwen-code at this historical checkpoint.

Blocker classes: `BLOCKED_LIVE_HARNESS_NOT_IMPLEMENTED`,
`BLOCKED_ADAPTER_RUNNER_NOT_IMPLEMENTED`.

The next action from this checkpoint was completed on 2026-07-29 by
implementing a bounded qwen-code adapter runner and live harness that convert
`stream-json` output into portable host-operation receipts, prove usage
attestation across the conformance and calibration profiles, and enforce
invocation, token and wall-clock caps.
