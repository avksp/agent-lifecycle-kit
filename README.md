# Agent Lifecycle Kit

[Русская версия](docs/guides/README.ru.md)

Agent Lifecycle Kit is a provider-neutral workflow distribution for turning a
software request into a reviewed SDD specification, a frozen agent-ready plan,
controlled implementation, independent implementation audit, and reproducible
final verdict.

It is distributed as one repository with one semantic core and native host
projections for Codex, Claude Code, Cursor, Hermes, and OpenCode.

## Current status

`v0.1.1` is a tagged source release. The repository now contains root-level
publication manifests for Codex, Claude Code, and Cursor, plus Hermes and
OpenCode projection metadata.

The adapters are still `EXPERIMENTAL`: they have offline contract coverage and
fail-closed descriptors, but they are not `VERIFIED` until each host has live
install and lifecycle conformance evidence. Public directory publication also
depends on each host marketplace review process.

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
`profiles/small-context-profile.v1.json` defines 8k, 16k, 32k, and 64k windows,
reserves output space, limits the active packet and state summary, and forbids
silent truncation.

If a rendered envelope does not fit, the controller must split the task,
request a larger context, or block the run. Older context and tool output are
represented by hashable summaries and evidence identities.

## Distribution layout

A universal distribution does not mean one manifest format. The same core is
projected into each host's native loading model:

| Host | Release artifact | Status |
| --- | --- | --- |
| Codex | `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` | Experimental marketplace-ready source projection |
| Claude Code | `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` | Experimental marketplace-ready source projection |
| Cursor | `.cursor-plugin/plugin.json` and `.cursor-plugin/marketplace.json` | Experimental source projection for public or team marketplace review |
| Hermes | `skills.sh.json`, shared `skills/`, and `adapters/hermes/*` | Experimental direct-skill/tap projection |
| OpenCode | `opencode.json`, shared `skills/`, and `adapters/opencode/*` | Experimental local/npm-ready projection metadata |

The root repository is the canonical plugin root for Codex, Claude Code, and
Cursor. The older `adapters/<host>/` directories remain offline conformance
projections and host-specific metadata; users should install from the root
package unless a future release explicitly publishes a materialized adapter
package.

## Installation and publication

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
agent-lifecycle context render --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
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

Implemented core CLI groups are `version`, `schema`, `workflow status`,
`workflow next`, `workflow block`, `workflow resolve`, `workflow task-start`,
`workflow task-result`, `workflow task-accept`, `workflow finalize`,
`audit ownership`, `tier resolve`, `context profile-check`, `context check`,
`context render`, and `neutrality`. Other lifecycle groups are reserved and
fail closed with a stable `agent-lifecycle-error.v1` response until their core
modules land.

Tests use only the Python standard library:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
```

### Codex

Install from the tagged source marketplace:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref v0.1.1
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
```

You can also browse configured marketplaces with `/plugins`. Start a new Codex
session after installation so the bundled skills are loaded.

For public Plugins Directory publication, submit the root package as a
skills-only plugin through the OpenAI plugin submission portal. Do not claim
`VERIFIED` until live Codex install and lifecycle conformance evidence is
published in the support matrix.

### Claude Code

Add the marketplace and install the plugin:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

In an interactive Claude Code session, the equivalent slash flow is:

```text
/plugin marketplace add avksp/agent-lifecycle-kit
/plugin install agent-lifecycle-kit@agent-lifecycle-kit
/reload-plugins
```

Plugin skills are namespaced by plugin name, for example
`/agent-lifecycle-kit:agent-workflow-orchestrator`.

For inclusion in the Anthropic-managed public directory, submit the plugin for
Claude's external plugin review. The repo-level marketplace is enough for
private or community distribution, but not a public-directory approval claim.

### Cursor

For local validation before submission, symlink or copy the repository into
Cursor's local plugin directory:

```bash
mkdir -p ~/.cursor/plugins/local
ln -s /path/to/agent-lifecycle-kit ~/.cursor/plugins/local/agent-lifecycle-kit
```

Then restart Cursor or run `Developer: Reload Window`. After local validation,
submit the public repository at `https://cursor.com/marketplace/publish`.

For Teams or Enterprise, import the GitHub repository as a team marketplace
from Dashboard -> Plugins. After public approval, install from the Cursor
Marketplace or Customize panel. If your Cursor build supports chat-based
plugin installation, use:

```text
/add-plugin agent-lifecycle-kit
```

### Hermes

Hermes can install the shared skills directly. To install all lifecycle skills
from the tagged release:

```bash
for skill in agent-first-planning audit-agent-plan agent-plan-to-workers agent-workflow-orchestrator audit-plan-implementation; do
  hermes skills install "https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/v0.1.1/skills/${skill}/SKILL.md"
done
```

The root `skills.sh.json` provides tap/category metadata for hosts that read
skills.sh-compatible indexes. `adapters/hermes/*` contains experimental
registry and slash-command projection metadata. It is not a live Hermes plugin
verification claim.

### OpenCode

OpenCode loads plugins and skills through separate mechanisms. For a project
install, copy the shared skills and adapter into the target project:

```bash
KIT=/path/to/agent-lifecycle-kit
mkdir -p .opencode/skills .opencode/plugins
cp -R "$KIT"/skills/* .opencode/skills/
cp "$KIT"/adapters/opencode/plugins/agent-lifecycle-kit.js .opencode/plugins/
```

For user-level install:

```bash
KIT=/path/to/agent-lifecycle-kit
mkdir -p ~/.config/opencode/skills ~/.config/opencode/plugins
cp -R "$KIT"/skills/* ~/.config/opencode/skills/
cp "$KIT"/adapters/opencode/plugins/agent-lifecycle-kit.js ~/.config/opencode/plugins/
```

The repository root also includes `opencode.json` for source checkout testing.
A future npm package can point to the same adapter, but no npm publication is
claimed by `v0.1.1`.

## Usage

Ask the host to run the full lifecycle through `agent-workflow-orchestrator`:

```text
Use the agent-workflow-orchestrator skill.

Task: <describe the required outcome>.

Ask only blocking clarification questions. Build and independently review an
SDD production-ready plan until it is ready to freeze. Request authorization
before implementation. Validate and independently review every task attempt.
Run the final audit and terminal review before reporting completion.
```

Host-specific explicit invocation may be used when available:

- Codex: select Agent Lifecycle Kit or ask Codex to use
  `agent-workflow-orchestrator`
- Claude Code: `/agent-lifecycle-kit:agent-workflow-orchestrator`
- Cursor: ask Agent to use `agent-workflow-orchestrator`
- Hermes: run `/agent-workflow-orchestrator` after installing the skill
- OpenCode: ask the agent to load `agent-workflow-orchestrator` through its
  native skill tool

The release support matrix is authoritative for exact namespaced syntax. An
experimental adapter projection is not a live runtime compatibility claim.

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
- The repository and all samples, fixtures, and evaluations must remain free of
  source-project information.
- Adapters may translate discovery, invocation, approvals, subagents, and host
  operations, but they may not reimplement lifecycle semantics.
- Install only trusted releases. Native plugins and hooks may execute code with
  the permissions granted by their host.
- Check the release support matrix before relying on a host adapter.

## Documentation

- [Russian README](docs/guides/README.ru.md)
- [Adapter support matrix](docs/adapters/support-matrix.md)
- [Modular controller architecture](docs/architecture/modular-controller.md)
- [Codex plugin documentation](https://learn.chatgpt.com/docs/build-plugins)
- [Claude Code plugin documentation](https://code.claude.com/docs/en/plugins)
- [Cursor plugin documentation](https://cursor.com/docs/plugins)
- [Hermes skills documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [OpenCode skills](https://opencode.ai/docs/skills/)
- [OpenCode plugins](https://opencode.ai/docs/plugins/)

## License

Licensed under the [Apache License 2.0](LICENSE).
