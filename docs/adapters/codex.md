# Codex adapter

The Codex projection packages the shared lifecycle skills and a Codex plugin
manifest. The root repository is the canonical Codex plugin root; `adapters/codex/`
remains host-specific projection metadata rather than a
separate lifecycle implementation.

Install from the tagged source marketplace:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref vX.Y.Z
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
```

`adapters/codex/` is `VERIFIED` for the tested Codex CLI 0.145.0 host range
recorded in `adapters/codex/adapter.descriptor.json`.

The local live evidence covers live conformance, live host operation coverage,
live calibration, and one ALK lifecycle proof. It does not claim public Plugins
Directory approval, official marketplace review, production platform promotion,
or universal adapter support. See `docs/adapters/evidence/codex-cli-0.6.0.md`.

## Qualified local launch

Codex CLI `0.147.0` has a separate version-bound local launch profile. Generate
and preflight it before a frozen `start --launch` call. This qualification does
not replace the `0.145.0` full adapter evidence range and does not promote
usage accounting beyond `FIXTURE_ONLY`. See [Qualified host
launch](../reference/qualified-host-launch.md).

The same exact version has a planning-only candidate, but its current status is
`PLANNING_ONLY_UNSUPPORTED`: no live containment receipt promotes it yet.
`start --mode plan --launch` therefore fails closed. See [Planning-only
adapter launch](../reference/planning-only-launch.md).

## Use ALK with Codex

After installing the plugin and restarting Codex, open the target project and
ask: `Use the agent-workflow-orchestrator skill for this task: <task>`. Codex
owns the model and tools; the skill guides it to call ALK and preserve the
lifecycle artifacts.

```text
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle through reviewed planning, plan freeze,
implementation audits and accepted final proof.
Task: <describe the task or name the Markdown file to read>
```

For a deterministic entrypoint outside the Codex session:

```bash
agent-lifecycle start --adapter codex --file task.md
```

This command creates ALK intake and does not start Codex by default. Plugin
installation alone is not lifecycle proof. See [Using ALK with an
adapter](usage-modes.md).
