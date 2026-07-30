# Install for agents

This guide is for agent hosts and operators installing Agent Lifecycle Kit from
a source checkout or tagged repository release.

## Core CLI

Use an isolated environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
agent-lifecycle version
```

Without installation, run from a checkout:

```bash
PYTHONPATH=src python -m agent_lifecycle version
PYTHONPATH=src python -m agent_lifecycle schema list
```

## Required operator checks

Before an agent executes work from a plan package:

```bash
agent-lifecycle plan check --manifest work/release-0-5/plan.manifest.json --lock work/release-0-5/plan.lock.json
agent-lifecycle plan acceptance-check --manifest work/release-0-5/plan.manifest.json --acceptance work/release-0-5/acceptance-criteria.md
agent-lifecycle task compile --manifest work/release-0-5/plan.manifest.json --out-dir work/release-0-5/workflow/task-packets
agent-lifecycle audit ownership --manifest work/release-0-5/plan.manifest.json --base HEAD --fail-on-unowned --fail-on-forbidden
```

For adapter evidence:

```bash
agent-lifecycle adapter validate --descriptor adapters/claude/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter event-check --event events/001-session-started.json --event events/002-task-launched.json --event events/003-task-completed.json
```

## Host plugins

Install host projections from the repository root unless a future release ships
a separate materialized adapter package.

Codex:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref v0.5.0
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
```

Claude Code:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

Cursor local validation:

```bash
mkdir -p ~/.cursor/plugins/local
ln -s /path/to/agent-lifecycle-kit ~/.cursor/plugins/local/agent-lifecycle-kit
```

OpenCode:

```bash
KIT=/path/to/agent-lifecycle-kit
mkdir -p .opencode/skills .opencode/plugins
cp -R "$KIT"/skills/* .opencode/skills/
cp "$KIT"/adapters/opencode/plugins/agent-lifecycle-kit.js .opencode/plugins/
```

## Status boundary

Adapters remain `EXPERIMENTAL` until live install, lifecycle conformance, usage
attestation and support-matrix evidence are published for that host. A green
offline adapter descriptor or event stream is not a `VERIFIED` claim.

Runs must not be marked complete unless final audit includes a valid
`agent-completion-signal.v1` with `PASS` status or an explicit `WAIVED` signal
with evidence. Human-only work must pause in workflow state and resume from an
external-action receipt rather than being reported as completed by prose.
