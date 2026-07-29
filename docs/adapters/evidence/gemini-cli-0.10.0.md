# Gemini CLI 0.10.0 adapter evidence

Status: scaffold and inspection passed; support is `EXPERIMENTAL`.

Scope:

- Host: Gemini CLI `0.46.0`.
- Adapter descriptor: `adapters/gemini-cli/adapter.descriptor.json`.
- Capability manifest: `adapters/gemini-cli/capabilities.manifest.json`.
- Raw inspection report:
  `tasks/release-0-10/evidence/gemini-cli/inspection/gemini-cli-inspection-report.json`.

Safe inspection result:

- descriptor validation: `PASS`;
- scaffold projection files: `PASS`;
- `gemini --version`: `PASS`;
- `gemini --help`: `PASS`;
- `gemini skills --help`: `PASS`;
- `gemini extensions --help`: `PASS`;
- `gemini mcp --help`: `PASS`;
- `gemini gemma --help`: `PASS`.

Discovered surfaces:

- headless execution supports `--prompt`;
- stream events are exposed through `--output-format stream-json`;
- model selection exposes `--model`;
- permission behavior exposes `--yolo`, `--approval-mode` and `--sandbox`, with
  ALK policy still fail-closed;
- skills, extensions, MCP and local Gemma routing command surfaces are present;
- no safe auth-status command was discovered in the inspected help surface;
- a bounded live canary on the current local setup returns an unsupported
  Gemini Code Assist individual-client tier error before a receipt can be
  captured.

Non-promotion decision:

Gemini CLI is not promoted in this evidence note. No live host conformance
receipt, usage/calibration receipt, or lifecycle final proof has been accepted
for Gemini CLI.

Blocker class: `BLOCKED_UNSUPPORTED_CLIENT_TIER`.

Next action: configure a supported Gemini/Antigravity setup, then rerun the
bounded Gemini CLI live harness with explicit invocation, token and wall-clock
caps and validate the live host receipt, live calibration receipt and lifecycle
final proof before any support-matrix promotion.
