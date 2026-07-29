# Kimi Code 0.12.0 adapter evidence

Status: inspection and bounded harness shape passed; support is
`EXPERIMENTAL`.

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
- bounded receipt normalization is implemented in
  `tools/live_hosts/kimi_code_harness.py`, using headless `--prompt` and
  post-invocation clean-worktree checks;
- local `kimi provider list` reports no configured providers, so usage
  attestation remains unproven until a provider/model alias is configured and a
  live receipt is captured and validated.

Non-promotion decision:

Kimi Code is not promoted in this evidence note. No live host conformance
receipt, usage/calibration receipt, or lifecycle final proof has been accepted
for Kimi Code.

Blocker class: `BLOCKED_HOST_MODEL_NOT_CONFIGURED`.

Next action: configure a Kimi Code provider/model alias outside the portable
core, then run the bounded live harness with explicit invocation, token and
wall-clock caps and validate the resulting live host conformance receipt, live
calibration receipt, and lifecycle proof before any support-matrix promotion.
