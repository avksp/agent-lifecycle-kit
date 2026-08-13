# OpenCode adapter

The OpenCode projection packages shared lifecycle skills, root `opencode.json`,
an OpenCode JS adapter under `adapters/opencode/`, and a derived capability
manifest at `adapters/opencode/capabilities.manifest.json`.

OpenCode-specific code projects lifecycle planning, freeze, workflow, review and
final-audit commands while ALK core remains the source of their semantics.

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

The verified scope covers OpenCode CLI `1.18.9`, the tested host-local model
binding and the evidence summary above.

## Launch through a verified local profile

OpenCode `1.18.15` has a separate version-bound local launch profile. Generate
and preflight it before a frozen `start --launch` call. The profile uses the
approved process arguments; the full adapter evidence range remains `1.18.9`,
and token accounting is `FIXTURE_ONLY`. See [Frozen-task launch through a verified
profile](../reference/qualified-host-launch.md).

The planning-only route has status `PLANNING_ONLY_UNSUPPORTED`; its
qualification path uses a safe native planning profile and live containment
evidence. See [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with OpenCode

After copying the shared skills and JS projection into the configured OpenCode
directories, restart the host and ask: `Use the agent-workflow-orchestrator
skill for this task: <task>`. OpenCode owns the selected provider, model and
tools.

```text
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle through reviewed planning, plan freeze,
implementation audits and accepted final proof.
Task: <describe the task or name the Markdown file to read>
```

For the command route:

```bash
agent-lifecycle start --adapter opencode --file task.md
```

The command creates ALK intake. For host execution, use the launch route through
a verified profile. See [Using ALK with an adapter](usage-modes.md).
