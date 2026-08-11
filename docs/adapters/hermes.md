# Hermes adapter

The Hermes projection packages shared lifecycle skills, root `skills.sh.json`,
Hermes registry/slash-command metadata under `adapters/hermes/`, and a derived
capability manifest at `adapters/hermes/capabilities.manifest.json`.

Install individual skills directly from the tagged source release, for example:

```bash
hermes skills install https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/vX.Y.Z/skills/agent-workflow-orchestrator/SKILL.md
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

The current source tree is `VERIFIED` for Hermes Agent `v0.19.0` only. The
accepted live evidence was captured on 2026-07-29 with host-local model
binding, bounded subscription resource caps, live conformance through the host
receipt, live calibration, and an ALK lifecycle final proof. The redacted live
summary is
`docs/adapters/evidence/hermes-host-local-live-2026-07-29.md`.

This does not claim public directory approval, production promotion, or
compatibility with untested Hermes versions.

## Planning-only launch status

Exact-version profile: `0.19.0`. Profile status: `UNSUPPORTED`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. A one-shot native tool-denial boundary has not been verified for this contract.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter hermes --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/hermes.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/hermes.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/hermes.json
```

A successful version preflight does not authorize planning launch.
`managedLaunch.status` remains `WRAPPER_ONLY`, and adapter maturity cannot
promote planning support. See [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with Hermes

After installing the tagged lifecycle skill, invoke the shipped command inside
Hermes:

```text
/agent-lifecycle-kit:agent-workflow-orchestrator Follow the full ALK lifecycle through reviewed planning, plan freeze, implementation audits and accepted final proof. Task: <task or Markdown file>
```

For the command route outside Hermes:

```bash
agent-lifecycle start --adapter hermes --file task.md
```

The first route is host-guided; the second does not start Hermes by default.
Neither skill installation nor a slash command alone is lifecycle proof. See
[Using ALK with an adapter](usage-modes.md).
