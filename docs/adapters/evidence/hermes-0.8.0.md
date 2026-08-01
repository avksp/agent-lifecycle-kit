# Hermes 0.8.0 adapter evidence

Status: inspection and preflight passed; this historical non-promotion note is
superseded by the 2026-07-29 live evidence.

Scope:

- Host: Hermes Agent `v0.19.0`.
- Adapter descriptor: `adapters/hermes/adapter.descriptor.json`.
- Capability manifest: `adapters/hermes/capabilities.manifest.json`.
- Registry metadata: `adapters/hermes/hermes.registry.json`.
- Slash-command metadata: `adapters/hermes/slash-commands.json`.
- Raw inspection report:
  `work/release-0-8/evidence/hermes/inspection/hermes-inspection-report.json`.
- Raw preflight report:
  `work/release-0-8/evidence/hermes/inspection/hermes-preflight-report.json`.

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

Historical non-promotion decision:

Hermes was not promoted by this evidence note. At the time, no live host
conformance receipt, usage/calibration receipt, or lifecycle final proof had
been accepted for Hermes. The support matrix therefore had to remain
`EXPERIMENTAL` until those gates passed for a concrete Hermes version range.

Historical blocker class: `BLOCKED_HOST_LOCAL_MODEL_BINDING`.

Next action: bind `profiles/hosts/hermes-live-profile.v1.json` to real
host-local Hermes provider/model identifiers, then rerun bounded live host
conformance, usage calibration and lifecycle proof with explicit live-run budget
caps.

Superseding evidence:

- `docs/adapters/evidence/hermes-host-local-live-2026-07-29.md`;
- `work/release-0-8/evidence/hermes/live-host-conformance-hermes.json`;
- `work/release-0-8/evidence/hermes/live-calibration-verification-hermes.json`;
- `work/release-0-8/evidence/hermes/full-lifecycle/final/final-proof.json`.
