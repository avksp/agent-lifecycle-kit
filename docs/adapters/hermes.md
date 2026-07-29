# Hermes adapter

The Hermes projection packages shared lifecycle skills, root `skills.sh.json`,
Hermes registry/slash-command metadata under `adapters/hermes/`, and a derived
capability manifest at `adapters/hermes/capabilities.manifest.json`.

Install individual skills directly from the tagged source release, for example:

```bash
hermes skills install https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/v0.6.1/skills/agent-workflow-orchestrator/SKILL.md
```

Validate the source projection before any live run:

```bash
agent-lifecycle adapter validate --descriptor adapters/hermes/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/hermes/adapter.descriptor.json --skip-host-commands
python tools/release/validate_adapter_conformance.py --baseline conformance/core/adapter-baseline.v1.json --host hermes --evidence <adapter-conformance-evidence.json>
```

Hermes Agent `v0.19.0` has passed safe local inspection for version/help
surfaces, headless oneshot mode, usage-file support, model/provider selection,
permission flags, skills, auth and status command discovery. The redacted
summary is `docs/adapters/evidence/hermes-0.8.0.md`.

Hermes availability is part of the standalone release target, but remains
`EXPERIMENTAL` until live Hermes conformance, usage calibration and lifecycle
proof evidence are accepted in the support matrix. Current blocker:
`BLOCKED_HOST_LOCAL_MODEL_BINDING`; the live profile still needs real
host-local Hermes provider/model identifiers before a bounded live run can
produce useful promotion evidence.
