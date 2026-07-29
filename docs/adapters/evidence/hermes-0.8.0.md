# Hermes 0.8.0 adapter evidence

Status: inspection and preflight passed; support remains `EXPERIMENTAL`.

Scope:

- Host: Hermes Agent `v0.19.0`.
- Adapter descriptor: `adapters/hermes/adapter.descriptor.json`.
- Capability manifest: `adapters/hermes/capabilities.manifest.json`.
- Registry metadata: `adapters/hermes/hermes.registry.json`.
- Slash-command metadata: `adapters/hermes/slash-commands.json`.
- Raw inspection report:
  `tasks/release-0-8/evidence/hermes/inspection/hermes-inspection-report.json`.
- Raw preflight report:
  `tasks/release-0-8/evidence/hermes/inspection/hermes-preflight-report.json`.

Safe inspection result:

- descriptor validation: `PASS`;
- root `skills.sh.json` skill config: `PASS`;
- Hermes registry metadata: `PASS`;
- Hermes slash-command metadata: `PASS`;
- `hermes --version`: `PASS`;
- `hermes --help`: `PASS`;
- `hermes chat --help`: `PASS`;
- `hermes skills --help`: `PASS`;
- `hermes auth --help`: `PASS`;
- `hermes status --help`: `PASS`.

Discovered surfaces:

- headless execution is available through `--oneshot`;
- usage reporting is exposed through `--usage-file` and still requires live
  receipt validation;
- model selection exposes `--model` and `--provider`;
- permission behavior exposes `--yolo` and `--safe-mode`, with ALK policy still
  fail-closed;
- skills management is available through `hermes skills`;
- auth command surface is discovered, but local credential state is intentionally
  not disclosed in committed evidence.

Non-promotion decision:

Hermes is not promoted in this evidence note. No live host conformance receipt,
usage/calibration receipt, or lifecycle final proof has been accepted for
Hermes. The support matrix must remain `EXPERIMENTAL` until those gates pass for
a concrete Hermes version range.

Blocker class: `BLOCKED_HOST_LOCAL_MODEL_BINDING`.

Next action: bind `profiles/hosts/hermes-live-profile.v1.json` to real
host-local Hermes provider/model identifiers, then rerun bounded live host
conformance, usage calibration and lifecycle proof with explicit live-run budget
caps.
