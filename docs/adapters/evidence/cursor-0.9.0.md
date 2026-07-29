# Cursor 0.9.0 adapter evidence

Status: inspection and preflight passed; support remains `EXPERIMENTAL`.

Scope:

- Host: Cursor Agent `2026.07.23-e383d2b`.
- Local subscription tier: `Free`.
- Adapter descriptor: `adapters/cursor/adapter.descriptor.json`.
- Capability manifest: `adapters/cursor/capabilities.manifest.json`.
- Raw inspection report:
  `tasks/release-0-9/evidence/cursor/inspection/cursor-inspection-report.json`.
- Raw preflight report:
  `tasks/release-0-9/evidence/cursor/inspection/cursor-preflight-report.json`.

Safe inspection result:

- descriptor validation: `PASS`;
- root Cursor plugin metadata: `PASS`;
- adapter-local Cursor plugin metadata: `PASS`;
- `cursor agent --version`: `PASS`;
- `cursor agent --help`: `PASS`;
- `cursor agent status --help`: `PASS`;
- `cursor agent about --help`: `PASS`;
- `cursor agent about`: `PASS`, account identifier redacted;
- `cursor agent models`: `PASS`, model names redacted in committed summary.

Discovered surfaces:

- headless execution supports `cursor agent --print`;
- stream events are exposed through `--output-format stream-json`;
- model selection exposes `--model`;
- permission behavior exposes `--force`, `--yolo` and `--auto-review`, with
  ALK policy still fail-closed;
- auth state is logged-in but account identifier is redacted;
- local subscription tier is `Free`.

Non-promotion decision:

Cursor is not promoted in this evidence note. A bounded smoke run on the local
Free subscription would spend limited user resources without satisfying the
required production usage/cost calibration and final lifecycle proof gates. The
support matrix must remain `EXPERIMENTAL` until those gates pass under an
explicit operator-approved budget.

Blocker class: `BLOCKED_FREE_SUBSCRIPTION_PROMOTION_EVIDENCE`.

Next action: rerun Cursor live host conformance, usage calibration and lifecycle
proof only after an operator approves explicit invocation, token and wall-clock
caps for a Cursor environment whose receipts can satisfy promotion evidence.
