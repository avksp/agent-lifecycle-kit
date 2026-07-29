# OpenCode 0.7.0 adapter evidence

Status: inspection passed; support remains `EXPERIMENTAL`.

Scope:

- Host: OpenCode CLI `1.18.9`.
- Adapter descriptor: `adapters/opencode/adapter.descriptor.json`.
- Capability manifest: `adapters/opencode/capabilities.manifest.json`.
- Raw inspection report:
  `tasks/release-0-7/evidence/opencode/inspection/opencode-inspection-report.json`.
- Offline conformance report:
  `tasks/release-0-7/evidence/conformance/adapter-conformance-verification.json`.

Safe inspection result:

- descriptor validation: `PASS`;
- root `opencode.json` plugin config: `PASS`;
- adapter-local `opencode.json` plugin config: `PASS`;
- `opencode --version`: `PASS`;
- `opencode auth --help`: `PASS`;
- `opencode run --help`: `PASS`;
- `opencode export --help`: `PASS`;
- `opencode stats --help`: `PASS`.

Discovered surfaces:

- headless run command supports `--format json` and `--dir`;
- permission behavior exposes `--auto`, with ALK policy still fail-closed;
- model selection exposes `--model`;
- event stream support is discovered through run JSON output and still requires
  receipt validation;
- usage attestation is discovered through stats/run JSON output and still
  requires live receipts;
- auth command surface is discovered, but local credential state is intentionally
  not disclosed in committed evidence.

Non-promotion decision:

OpenCode is not promoted in this evidence note. No live host conformance
receipt, usage/calibration receipt, or lifecycle final proof has been accepted
for OpenCode. The support matrix must remain `EXPERIMENTAL` until those gates
pass for a concrete OpenCode version range.

Blocker class: `BLOCKED_HOST_LOCAL_MODEL_BINDING`.

Next action: bind `profiles/hosts/opencode-live-profile.v1.json` to real
host-local OpenCode model identifiers, then rerun bounded live host conformance,
usage calibration and lifecycle proof with explicit live-run budget caps.
