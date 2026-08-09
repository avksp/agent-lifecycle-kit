# OpenCode adapter

The OpenCode projection packages shared lifecycle skills, root `opencode.json`,
an OpenCode JS adapter under `adapters/opencode/`, and a derived capability
manifest at `adapters/opencode/capabilities.manifest.json`.

OpenCode-specific code must not reimplement lifecycle planning, freeze,
workflow, review or final-audit semantics.

OpenCode loads plugins and skills separately. Copy `skills/*` into
`.opencode/skills/` or `~/.config/opencode/skills/`, and copy
`adapters/opencode/plugins/agent-lifecycle-kit.js` into the matching
`.opencode/plugins/` location.

Validate the source projection before any live run:

```bash
agent-lifecycle adapter validate --descriptor adapters/opencode/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/opencode/adapter.descriptor.json --skip-host-commands
python tools/release/validate_adapter_conformance.py --baseline conformance/core/adapter-baseline.v1.json --host opencode --evidence <adapter-conformance-evidence.json>
```

OpenCode CLI `1.18.9` has passed safe local inspection for version/help
surfaces, headless JSON run mode, model selection, permission flag discovery,
export and stats command discovery. The redacted summary is
`docs/adapters/evidence/opencode-0.7.0.md`.

The current source tree is `VERIFIED` for OpenCode CLI `1.18.9` only. The
accepted live evidence was captured on 2026-07-29 with host-local model
binding, bounded subscription resource caps, live conformance through the host
receipt, live calibration, and an ALK lifecycle final proof. The redacted live
summary is
`docs/adapters/evidence/opencode-host-local-live-2026-07-29.md`.

This does not claim npm publication, public directory approval, production
promotion, or compatibility with untested OpenCode versions.

## Qualified local launch

OpenCode `1.18.15` has a separate version-bound local launch profile. Generate
and preflight it before a frozen `start --launch` call. The profile does not
use `--auto`, change the `1.18.9` full adapter evidence range, or qualify token
accounting for S1/S2. See [Qualified host
launch](../reference/qualified-host-launch.md).
