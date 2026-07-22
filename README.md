# Agent Lifecycle Kit

[Русская версия](docs/guides/README.ru.md)

Agent Lifecycle Kit is a provider-neutral workflow distribution for turning a
software request into a reviewed specification, a frozen agent-ready plan,
audited implementation, and a reproducible final verdict.

It is distributed as one repository with one semantic core and multiple native
host adapters. It is not a Codex-only plugin: Codex, Claude Code, Cursor,
Hermes, and OpenCode use their own installation and capability models.

> **Pre-release status**
>
> The current `main` branch is a release-candidate source tree. It contains
> offline adapter projections and the source-mode core CLI for workflow,
> schema, tier, compact context, ownership, and neutrality checks. Do not treat
> marketplace installation commands below as available until a tagged release
> publishes the referenced manifests and its support matrix marks the adapter
> `EXPERIMENTAL` or `VERIFIED`.

## What the kit does

The complete lifecycle is:

```text
request
  -> clarification when required
  -> SDD specification
  -> independent specification review and refinement
  -> production-ready agent plan
  -> independent plan review and refinement
  -> immutable freeze
  -> task packet compilation
  -> authorized implementation
  -> controller-owned validation and independent review per task
  -> remediation or contract change when required
  -> final audit, terminal review, and reproducible completion proof
```

The lifecycle has five canonical skills:

- `agent-first-planning`
- `audit-agent-plan`
- `agent-plan-to-workers`
- `agent-workflow-orchestrator`
- `audit-plan-implementation`

The skills are thin entry points. Specifications, plans, locks, task packets,
run state, evidence, budgets, and audit semantics are owned by the shared
deterministic core rather than reimplemented in each host adapter.

## Compact context mode

Small-context hosts are supported through a deterministic context profile, not
through prompt-only truncation. The bundled
`profiles/small-context-profile.v1.json` defines 8k, 16k, 32k, and 64k
windows, reserves output space, limits the active packet and state summary, and
forbids silent truncation. If a rendered envelope does not fit, the controller
must split the task, request a larger context, or block the run.

The compact envelope contains only the active role, latest user instruction,
active task packet projection, exact write set, acceptance/evidence ids, and a
structured state summary. Older context and tool output are represented by
hashable summaries and evidence identities.

## One distribution, native host adapters

A universal distribution does not mean one manifest format. The release
projects the same core into the native format of each supported host:

| Host | Native release projection | Installation model |
| --- | --- | --- |
| Codex | `.codex-plugin/plugin.json` plus shared `skills/` | Codex marketplace |
| Claude Code | `.claude-plugin/plugin.json` plus shared `skills/` and Claude adapter metadata | Claude plugin marketplace or `--plugin-dir` for development |
| Cursor | `.cursor-plugin/plugin.json` plus shared `skills/` and Cursor adapter metadata | Cursor Marketplace and `/add-plugin` |
| Hermes | shared `skills/` plus Hermes registry/config and launcher metadata | Hermes adapter package or local registry/config projection |
| OpenCode | shared `skills/` plus an OpenCode JS/TS adapter | `.opencode/` directories or an npm plugin declared in `opencode.json` |
| Other hosts | versioned adapter contract and conformance suite | host-specific adapter package |

The first release targets these five hosts. A host is never described as
`VERIFIED` without bounded live conformance evidence. Offline-only adapters are
reported as `EXPERIMENTAL`, and unavailable safety-critical capabilities fail
closed.

## Installation

### Source-mode core CLI

For local development of the current repository:

```bash
python -m pip install -e .
agent-lifecycle version
agent-lifecycle schema list
agent-lifecycle workflow status --state <path-to-run.state.json>
agent-lifecycle workflow next --state <path-to-run.state.json>
agent-lifecycle workflow task-start --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --reason "<reason>"
agent-lifecycle workflow task-result --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --result <task-result.json> --reason "<reason>"
agent-lifecycle workflow task-accept --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --review <task-review.json> --reason "<reason>"
agent-lifecycle workflow finalize --state <path-to-run.state.json> --operation-id <id> --expected-revision <n> --source-revision <sha> --proof <final-proof.json> --reason "<reason>"
agent-lifecycle audit ownership --manifest <plan.manifest.json> --base <base-ref> --fail-on-unowned --fail-on-forbidden
agent-lifecycle tier resolve --request <tier-request.json>
agent-lifecycle context profile-check --profile profiles/small-context-profile.v1.json
agent-lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
agent-lifecycle-neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

The same commands can run without installation from a checkout:

```bash
PYTHONPATH=src python -m agent_lifecycle version
PYTHONPATH=src python -m agent_lifecycle schema list
PYTHONPATH=src python -m agent_lifecycle workflow status --state <path-to-run.state.json>
PYTHONPATH=src python -m agent_lifecycle workflow next --state <path-to-run.state.json>
PYTHONPATH=src python -m agent_lifecycle workflow task-start --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle workflow finalize --state <path-to-run.state.json> --operation-id <id> --expected-revision <n> --source-revision <sha> --proof <final-proof.json> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle audit ownership --manifest <plan.manifest.json> --base <base-ref> --fail-on-unowned --fail-on-forbidden
PYTHONPATH=src python -m agent_lifecycle tier resolve --request <tier-request.json>
PYTHONPATH=src python -m agent_lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

The currently implemented core CLI groups are `version`, `schema`,
`workflow status`, `workflow next`, `workflow block`, `workflow resolve`,
`workflow task-start`, `workflow task-result`, `workflow task-accept`, and
`workflow finalize`, `audit ownership`, `tier resolve`, `context profile-check`,
`context check`, `context render`, and `neutrality`. Other lifecycle groups are reserved and fail closed with a
stable `agent-lifecycle-error.v1` response until their core modules land.

Tests use only the Python standard library:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
```

### Codex

After a release marketplace is available:

```bash
codex plugin marketplace add <marketplace-repository-or-local-root>
codex plugin add agent-lifecycle-kit@<marketplace-name>
```

You can also browse configured marketplaces with `/plugins`. Start a new Codex
session after installation so the bundled skills and adapter are loaded.

### Claude Code

For a released marketplace:

```bash
claude plugin marketplace add <marketplace-repository-or-local-root>
claude plugin install agent-lifecycle-kit@<marketplace-name>
```

For local adapter development after the Claude manifest exists:

```bash
claude --plugin-dir <path-to-agent-lifecycle-kit>
```

Run `/reload-plugins` after installing or changing the local plugin. Claude
plugin skills are namespaced by plugin name.

### Cursor

After the adapter is published on the Cursor Marketplace, run this in Cursor
Agent chat:

```text
/add-plugin agent-lifecycle-kit
```

The release support matrix will state the minimum validated Cursor version and
whether local-path installation has passed the lifecycle canary.

### Hermes

Hermes uses the shared lifecycle skills through a Hermes-specific registry or
configuration projection plus a launcher adapter. The exact local registry path,
package name, and invocation syntax will be documented only after the Hermes
artifact exists and passes the Hermes conformance suite.

Until then, Hermes is a required adapter target for the standalone release
contract, not a verified runtime claim.

### OpenCode

OpenCode does not use the Codex, Claude, or Cursor manifest. A release will
contain an OpenCode projection with both the canonical skills and the runtime
adapter. For project-scoped installation it will be copied into:

```text
.opencode/skills/<skill-name>/SKILL.md
.opencode/plugins/agent-lifecycle-kit.{js,ts}
```

For user-scoped installation the equivalent roots are:

```text
~/.config/opencode/skills/<skill-name>/SKILL.md
~/.config/opencode/plugins/agent-lifecycle-kit.{js,ts}
```

If the adapter is published to npm, it can instead be declared in
`opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["<published-opencode-adapter-package>"]
}
```

The exact copy/install command and package name will be added only when the
corresponding release artifact exists and passes the OpenCode conformance
suite.

## Usage

Ask the host to run the full lifecycle through
`agent-workflow-orchestrator`. For example:

```text
Use the agent-workflow-orchestrator skill.

Task: <describe the required outcome>.

Ask only blocking clarification questions. Build and independently review an
SDD production-ready plan until it is ready to freeze. Request authorization
before implementation. Validate and independently review every task attempt.
Run the final audit and terminal review before reporting completion.
```

Host-specific explicit invocation may be used when available:

- Codex: select the installed plugin or bundled skill with `@`, or ask Codex to
  use `agent-workflow-orchestrator` from Agent Lifecycle Kit
- Claude Code: `/agent-lifecycle-kit:agent-workflow-orchestrator`
- Cursor: ask Agent to use `agent-workflow-orchestrator`
- Hermes: ask Hermes to load `agent-workflow-orchestrator` through the
  configured lifecycle-kit registry or launcher adapter
- OpenCode: ask the agent to load `agent-workflow-orchestrator` through its
  native skill tool

The release support matrix is authoritative for exact namespaced syntax. A
pre-release example is not an invocation compatibility claim.

### Stage-specific skills

Use `agent-first-planning` when you need clarification, an SDD specification,
and a production-ready plan without starting implementation:

```text
Use agent-first-planning to turn this request into an independently reviewable
SDD plan package. Stop before implementation.
```

Use `audit-agent-plan` for an independent findings-first review of a draft or
reopened plan:

```text
Use audit-agent-plan to review this complete plan revision. Do not implement
or silently repair it; return stable findings and a readiness verdict.
```

Use `agent-plan-to-workers` only after a reviewed plan is frozen:

```text
Use agent-plan-to-workers to compile this frozen plan into immutable task
packets. Do not redesign the DAG or ownership.
```

Use `agent-workflow-orchestrator` to run or resume the complete authorized
lifecycle:

```text
Use agent-workflow-orchestrator to resume the frozen run from durable state,
enforce its budgets and approvals, and route every task through review.
```

Use `audit-plan-implementation` for a read-only task-attempt or final
implementation audit:

```text
Use audit-plan-implementation for a findings-first audit against the frozen
plan, packet, changed files, tests, and evidence. Do not fix findings.
```

## Execution and approval policy

The durable workflow state is independent of chat history and native goal-mode
availability. A host with native background tasks can map them through its
adapter; another host can resume the same state sequentially.

Implementation starts only from a hash-verified frozen plan and immutable task
packet set. The default flow asks for authorization before execution.
Automatic execution is allowed only when the frozen run policy and host policy
both permit it. Contract changes, authority drift, missing evidence, exhausted
budgets, or unavailable mandatory capabilities block the run.

SDD tier selection is proposed by planning, checked by the deterministic
`tier resolve` rules, independently reviewed by `audit-agent-plan`, and then
frozen by the controller. Manual overrides may raise the tier; lowering a tier
requires resolver and independent review agreement.

## Compatibility and safety

- Core contracts do not embed provider names, model names, project paths, or
  credentials.
- The repository and all samples, fixtures, and evaluations must remain free
  of source-project information.
- Adapters may translate discovery, invocation, approvals, subagents, and host
  operations, but they may not reimplement lifecycle semantics.
- Install only trusted releases. Native plugins and hooks may execute code with
  the permissions granted by their host.
- Check the release support matrix before relying on a host adapter.

## Documentation

- [Russian README](docs/guides/README.ru.md)
- [Modular controller architecture](docs/architecture/modular-controller.md)
- [Codex plugin documentation](https://learn.chatgpt.com/docs/build-plugins)
- [Claude Code plugin documentation](https://code.claude.com/docs/en/plugins)
- [Cursor plugin documentation](https://cursor.com/docs/plugins)
- [Hermes skills documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [OpenCode skills](https://opencode.ai/docs/skills/)
- [OpenCode plugins](https://opencode.ai/docs/plugins/)

## License

Licensed under the [Apache License 2.0](LICENSE).
