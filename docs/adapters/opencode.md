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

The adapter remains `EXPERIMENTAL` until live OpenCode conformance, usage
calibration and lifecycle proof evidence are accepted in the support matrix.
Current blocker: `BLOCKED_HOST_LOCAL_MODEL_BINDING`; the live profile still
needs real host-local OpenCode model identifiers before a bounded live run can
produce useful promotion evidence.
