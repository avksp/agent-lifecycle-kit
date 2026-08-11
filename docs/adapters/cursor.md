# Cursor adapter

The Cursor projection packages shared lifecycle skills, root
`.cursor-plugin/plugin.json`, and root `.cursor-plugin/marketplace.json`.
`adapters/cursor/` remains an offline conformance projection and includes a
derived capability manifest at `adapters/cursor/capabilities.manifest.json`.

The lifecycle core remains outside Cursor-specific prompt text. Cursor-specific
integration should only translate invocation, discovery and approval surfaces.

For local validation before public submission, symlink the repository into
`~/.cursor/plugins/local/agent-lifecycle-kit` and reload Cursor. Public
Marketplace publication requires submitting the public repository through
Cursor's review flow.

Validate the source projection before any live run:

```bash
agent-lifecycle adapter validate --descriptor adapters/cursor/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/cursor/adapter.descriptor.json --skip-host-commands
python tools/release/validate_adapter_conformance.py --baseline conformance/core/adapter-baseline.v1.json --host cursor --evidence <adapter-conformance-evidence.json>
```

Cursor Agent `2026.07.23-e383d2b` has passed safe local inspection for
version/help surfaces, `--print` headless mode, stream JSON output, model
selection, permission flags, auth/about command discovery and model catalog
discovery. The local subscription tier is `Free`; account identifiers are
redacted in evidence. The summary is
`docs/adapters/evidence/cursor-0.9.0.md`.

The adapter remains `EXPERIMENTAL` until live Cursor conformance, usage
calibration and lifecycle proof evidence are accepted in the support matrix.
Current blocker: `BLOCKED_FREE_SUBSCRIPTION_PROMOTION_EVIDENCE`; bounded smoke
on the local Free subscription cannot replace usage/resource attestation or final
lifecycle proof.

## Planning-only launch status

Exact-version profile: `2026.07.23`. Profile status: `UNSUPPORTED`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The CLI does not yet have a verified bounded stdin result transport for this contract.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter cursor --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/cursor.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/cursor.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/cursor.json
```

A successful version preflight does not authorize planning launch.
`managedLaunch.status` remains `WRAPPER_ONLY`, and adapter maturity cannot
promote planning support. See [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with Cursor

Link the trusted checkout into Cursor's local plugin directory, reload Cursor,
open the target project and ask: `Use the agent-workflow-orchestrator skill for
this task: <task>`. This is host-guided use; it does not change Cursor's
`EXPERIMENTAL` adapter status.

```text
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle through reviewed planning, plan freeze,
implementation audits and accepted final proof.
Task: <describe the task or name the Markdown file to read>
```

For the command route:

```bash
agent-lifecycle start --adapter cursor --file task.md
```

The command creates review-gated intake and does not start Cursor by default.
See [Using ALK with an adapter](usage-modes.md).
