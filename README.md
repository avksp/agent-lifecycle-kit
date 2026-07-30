# Agent Lifecycle Kit

[Русская версия](docs/guides/README.ru.md)

Agent Lifecycle Kit is a provider-neutral workflow distribution for turning a
software request into a reviewed SDD specification, a frozen agent-ready plan,
controlled implementation, independent implementation audit, and reproducible
final verdict.

It is distributed as one repository with one semantic core and native host
projections for Codex, Claude Code, Cursor, Gemini CLI, Hermes, Kimi Code,
OpenCode, and qwen-code.

## Why it exists

Agentic software work breaks down when the plan, execution budget, writes,
reviews, and final proof live only in chat history. Agent Lifecycle Kit turns
those steps into explicit artifacts and gates so a task can be driven to a
defensible finish without losing control of quality or resource use.

Use it when you need:

- reviewed SDD planning before implementation starts;
- frozen task packets with bounded ownership and validation contracts;
- controlled execution with context, budget, and external-action gates;
- independent implementation audits before acceptance;
- host-specific adapter evidence instead of broad unsupported claims.

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
`profiles/small-context-profile.v1.json` defines 4k-strict, 8k, 16k, 32k, and
64k windows, reserves output space, limits the active packet and state summary,
limits evidence/tool-output summaries and recent verbatim user turns, and
forbids silent truncation.

If a rendered envelope does not fit, the controller must split the task,
request a larger context, or block the run. Older context and tool output are
represented by hashable summaries and evidence identities.

The conformance corpus includes a dedicated `4k-strict` scenario
(`S1-SMALL-CONTEXT-4K-STRICT-01`) in addition to the 8k baseline, so support for
sub-8k local models is verified as a separate contract path.

## Goal continuity

Long-running tasks can carry an optional `agent-goal-record.v1` artifact. It
binds the user's intent, the owner-visible outcome, constraints, evidence ids
and lifecycle lineage without copying the whole conversation into every
continuation prompt.

`agent-lifecycle goal summarize` renders an `agent-objective-snapshot.v1`
compact snapshot with the concise intent, owner outcome, constraints, digests
and the next workflow action. The snapshot is validated against the same
small-context profile as task packets, including `4k-strict`, so small local
models get enough working context without the full history. Larger models can
still inspect the full state, plan, evidence and final audit; the compact
snapshot is a continuation aid, not a replacement for review. If the record is
stale, points at another run or contradicts the current `completionCheck`,
validation fails closed before more tokens are spent. `workflow finalize` can
also bind a current goal record into the final proof through `--goal-record`.

See [goal continuity](docs/reference/goal-continuity.md).

## Controlled runner

The runner keeps a narrow `agent-runner-state.v1` execution-loop state around
existing workflow primitives. It validates allowed transitions,
attempt/reroute/split caps, billable-token caps, stop/resume requests and
remediation patch metadata. It does not replace workflow state and does not
execute host-specific code.

`agent-runner-snapshot.v1` gives small local models a compact view of runner
status, next allowed actions, budget counters and recent transitions. The
snapshot must fit the selected small-context profile, including `4k-strict`.
Larger models can still inspect the full workflow state, runner state, evidence
and reviews for quality-sensitive work.

See [controlled runner](docs/reference/runner.md).

## Live cost calibration

Synthetic replay baselines are useful for deterministic regression checks, but
they are not production-promotion evidence. Promotion requires a live,
usage-attested receipt validated against
`conformance/core/live-calibration-profile.v1.json` and
`conformance/core/budget-targets.v1.json`.

Lifecycle conformance for a promoted host is validated separately:

```bash
python tools/release/validate_live_host_conformance.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --baseline conformance/core/adapter-baseline.v1.json \
  --receipt-dir <live-host-receipts-dir> \
  --promoted-hosts codex \
  --evidence <live-host-conformance-evidence.json>
```

```bash
python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt-dir <live-calibration-receipts-dir> \
  --promoted-hosts codex \
  --evidence <live-calibration-evidence.json>
```

The validator rejects synthetic replay receipts, missing usage attestations,
unsupported hosts, missing required scenario/cohort coverage for that host,
quality regressions, and p95 budget overruns. A universal `VERIFIED` claim
requires one passing live host conformance receipt and one passing live cost
calibration receipt per host listed in the calibration profile.
See
[live cost calibration](docs/reference/live-cost-calibration.md).

## Model routing

Model routing is a deterministic provider-neutral core capability. The core
resolves a neutral model class for each phase or task attempt; host adapters map
that class to a configured provider/runtime model outside portable artifacts.
When a task attempt has `attemptModelRoute.requiresUsageReceipt=true`,
`workflow task-result` is fail-closed until a valid host-attested usage receipt
is provided.

```bash
agent-lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
agent-lifecycle model route --profile profiles/model-routing-profile.v1.json --request <model-route-request.json>
agent-lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
```

Portable classes are `no-model`, `budget`, `local-compact`, `standard-code`,
`local-standard-code`, `strong-reasoning`, `local-strong-review`, and
`specialist-review`. Local-only execution is supported, but final audit,
security review, performance review, production promotion, and S2 independent
review require an explicitly calibrated review-capable local class such as
`local-strong-review`; `local-compact` cannot silently satisfy those gates.

See [model routing](docs/reference/model-routing.md).

## Budget decisions

Budget caps are safety stops, not success criteria. When a model-backed attempt
exceeds an approved cap, the workflow enters `WAITING_FOR_BUDGET_DECISION`
instead of accepting the task. In manual mode an operator chooses whether to
continue, reroute, split, or abort. In auto mode the policy can reroute within a
bounded count, but critical review phases cannot silently downgrade to weaker
classes.

Budget modes are:

- `metered`: requires an approved USD cap.
- `subscription`: requires `maxInvocations` and a token or wall-clock cap.
- `local`: uses the same resource-cap rule as subscription mode.

See [budget reroute policy](docs/guides/budget-reroute-policy.md).

## Distribution layout

A universal distribution does not mean one manifest format. The source
distribution carries the support claims and evidence references summarized
below. The same deterministic core is projected into each host's native loading
model:

| Host | Release artifact | Maturity | Why |
| --- | --- | --- | --- |
| Codex | `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` | `VERIFIED` for Codex CLI 0.145.0 | Local live conformance, live usage calibration, and full ALK lifecycle proof passed. Public Plugins Directory approval is not claimed. |
| Claude Code | `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` | `VERIFIED` for Claude Code 2.1.220 | Local live conformance, live usage calibration, and full ALK lifecycle proof passed. Public directory approval is not claimed. |
| Cursor | `.cursor-plugin/plugin.json`, `.cursor-plugin/marketplace.json`, and `adapters/cursor/*` | `EXPERIMENTAL` | Safe inspection passed on a local Free tier, but usage/cost attestation and full lifecycle proof are not accepted yet. Marketplace approval is not claimed. |
| Gemini CLI | `adapters/gemini-cli/*` | `EXPERIMENTAL` | Safe inspection and bounded harness shape passed, but local live canary is blocked by the current unsupported Gemini Code Assist client tier. |
| Hermes | `skills.sh.json`, shared `skills/`, and `adapters/hermes/*` | `VERIFIED` for Hermes Agent v0.19.0 | Local live conformance, live usage calibration, and full ALK lifecycle proof passed. Public directory/publication approval is not claimed. |
| Kimi Code | `adapters/kimi-code/*` | `EXPERIMENTAL` | Safe inspection and bounded harness shape passed, but local live canary is blocked until a provider/model alias is configured. |
| OpenCode | `opencode.json`, shared `skills/`, and `adapters/opencode/*` | `VERIFIED` for OpenCode CLI 1.18.9 | Local live conformance, live usage calibration, and full ALK lifecycle proof passed. npm publication is not claimed. |
| qwen-code | `adapters/qwen-code/*` | `VERIFIED` for qwen-code 0.21.0 | Local live conformance, live usage calibration, and full ALK lifecycle proof passed on GLM 5.2. Public package approval is not claimed. |

`EXPERIMENTAL` means the adapter has source metadata, capability manifests, and
offline conformance checks, but it is not a live runtime compatibility claim. A
host becomes `VERIFIED` only after bounded live host conformance, usage/cost
calibration, and a full lifecycle proof are accepted for that exact host and
version range. A model smoke test alone is not enough.

The root repository is the canonical plugin root for Codex, Claude Code, and
Cursor. The older `adapters/<host>/` directories remain offline conformance
projections and host-specific metadata; users should install from the root
package unless a future release explicitly publishes a materialized adapter
package.

## Installation and publication

Examples that use `vX.Y.Z` expect a trusted GitHub release tag.

### Source-mode core CLI

For local development of the current repository:

```bash
python -m pip install -e .
agent-lifecycle version
agent-lifecycle diagnose
agent-lifecycle schema list
agent-lifecycle workflow status --state <path-to-run.state.json>
agent-lifecycle workflow next --state <path-to-run.state.json>
agent-lifecycle workflow task-start --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --reason "<reason>"
agent-lifecycle workflow task-result --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --result <task-result.json> --model-usage-receipt <model-usage-receipt.json> --reason "<reason>"
agent-lifecycle workflow task-accept --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --review <task-review.json> --reason "<reason>"
agent-lifecycle workflow finalize --state <path-to-run.state.json> --operation-id <id> --expected-revision <n> --source-revision <sha> --final-audit <final-audit.json> --proof <final-proof.json> --goal-record <goal-record.json> --reason "<reason>"
agent-lifecycle goal check --record <goal-record.json> --state <path-to-run.state.json> --current
agent-lifecycle goal summarize --record <goal-record.json> --state <path-to-run.state.json> --profile profiles/small-context-profile.v1.json --target-window 8k
agent-lifecycle goal update --record <goal-record.json> --state <path-to-run.state.json> --status READY_FOR_FINALIZATION --evidence-id <evidence-id> --reason "<reason>" --out <goal-record.updated.json>
agent-lifecycle runner start --state <path-to-run.state.json> --runner <runner.state.json> --operation-id <id> --reason "<reason>"
agent-lifecycle runner status --runner <runner.state.json> --state <path-to-run.state.json> --profile profiles/small-context-profile.v1.json --target-window 4k-strict
agent-lifecycle runner transition --runner <runner.state.json> --state <path-to-run.state.json> --request <runner-transition-request.json>
agent-lifecycle runner stop --runner <runner.state.json> --state <path-to-run.state.json> --operation-id <id> --expected-runner-revision <n> --reason "<reason>"
agent-lifecycle runner resume --runner <runner.state.json> --state <path-to-run.state.json> --operation-id <id> --expected-runner-revision <n> --reason "<reason>"
agent-lifecycle audit ownership --manifest <plan.manifest.json> --base <base-ref> --fail-on-unowned --fail-on-forbidden
agent-lifecycle tier resolve --request <tier-request.json>
agent-lifecycle specification check --specification <specification.json>
agent-lifecycle plan check --manifest <plan.manifest.json> --lock <plan.lock.json>
agent-lifecycle plan acceptance-check --manifest <plan.manifest.json> --acceptance <acceptance-criteria.md>
agent-lifecycle task compile --manifest <plan.manifest.json> --out-dir <task-packet-dir> --write
agent-lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
agent-lifecycle model route --profile profiles/model-routing-profile.v1.json --request <model-route-request.json>
agent-lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
agent-lifecycle context profile-check --profile profiles/small-context-profile.v1.json
agent-lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 4k-strict
agent-lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
agent-lifecycle context render --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
agent-lifecycle adapter validate --descriptor adapters/codex/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/opencode/adapter.descriptor.json --skip-host-commands
agent-lifecycle adapter install-plan --descriptor adapters/opencode/adapter.descriptor.json
agent-lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
agent-lifecycle adapter scaffold --host synthetic-host --target /tmp/agent-lifecycle-adapter-scaffold --dry-run
agent-lifecycle-neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

The same commands can run without installation from a checkout:

```bash
PYTHONPATH=src python -m agent_lifecycle version
PYTHONPATH=src python -m agent_lifecycle diagnose
PYTHONPATH=src python -m agent_lifecycle schema list
PYTHONPATH=src python -m agent_lifecycle workflow status --state <path-to-run.state.json>
PYTHONPATH=src python -m agent_lifecycle workflow next --state <path-to-run.state.json>
PYTHONPATH=src python -m agent_lifecycle workflow task-start --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle workflow finalize --state <path-to-run.state.json> --operation-id <id> --expected-revision <n> --source-revision <sha> --final-audit <final-audit.json> --proof <final-proof.json> --goal-record <goal-record.json> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle goal check --record <goal-record.json> --state <path-to-run.state.json> --current
PYTHONPATH=src python -m agent_lifecycle goal summarize --record <goal-record.json> --state <path-to-run.state.json> --profile profiles/small-context-profile.v1.json --target-window 8k
PYTHONPATH=src python -m agent_lifecycle goal update --record <goal-record.json> --state <path-to-run.state.json> --status READY_FOR_FINALIZATION --evidence-id <evidence-id> --reason "<reason>" --out <goal-record.updated.json>
PYTHONPATH=src python -m agent_lifecycle runner start --state <path-to-run.state.json> --runner <runner.state.json> --operation-id <id> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle runner status --runner <runner.state.json> --state <path-to-run.state.json> --profile profiles/small-context-profile.v1.json --target-window 4k-strict
PYTHONPATH=src python -m agent_lifecycle runner transition --runner <runner.state.json> --state <path-to-run.state.json> --request <runner-transition-request.json>
PYTHONPATH=src python -m agent_lifecycle runner stop --runner <runner.state.json> --state <path-to-run.state.json> --operation-id <id> --expected-runner-revision <n> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle runner resume --runner <runner.state.json> --state <path-to-run.state.json> --operation-id <id> --expected-runner-revision <n> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle audit ownership --manifest <plan.manifest.json> --base <base-ref> --fail-on-unowned --fail-on-forbidden
PYTHONPATH=src python -m agent_lifecycle tier resolve --request <tier-request.json>
PYTHONPATH=src python -m agent_lifecycle specification check --specification <specification.json>
PYTHONPATH=src python -m agent_lifecycle plan check --manifest <plan.manifest.json> --lock <plan.lock.json>
PYTHONPATH=src python -m agent_lifecycle plan acceptance-check --manifest <plan.manifest.json> --acceptance <acceptance-criteria.md>
PYTHONPATH=src python -m agent_lifecycle task compile --manifest <plan.manifest.json> --out-dir <task-packet-dir> --write
PYTHONPATH=src python -m agent_lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
PYTHONPATH=src python -m agent_lifecycle model route --profile profiles/model-routing-profile.v1.json --request <model-route-request.json>
PYTHONPATH=src python -m agent_lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
PYTHONPATH=src python -m agent_lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
PYTHONPATH=src python -m agent_lifecycle adapter validate --descriptor adapters/codex/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
PYTHONPATH=src python -m agent_lifecycle adapter inspect --descriptor adapters/opencode/adapter.descriptor.json --skip-host-commands
PYTHONPATH=src python -m agent_lifecycle adapter install-plan --descriptor adapters/opencode/adapter.descriptor.json
PYTHONPATH=src python -m agent_lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
PYTHONPATH=src python -m agent_lifecycle adapter scaffold --host synthetic-host --target /tmp/agent-lifecycle-adapter-scaffold --dry-run
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

Implemented core CLI groups are `version`, `diagnose`, `schema`, `workflow status`,
`workflow next`, `workflow block`, `workflow resolve`, `workflow task-start`,
`workflow task-result`, `workflow task-accept`, `workflow finalize`,
`audit ownership`, `tier resolve`, `context profile-check`, `context check`,
`context render`, `model profile-check`, `model route`, `model usage-check`,
`goal check`, `goal summarize`, `goal update`, `runner start`, `runner status`,
`runner transition`, `runner stop`, `runner resume`, `specification check`,
`plan check`, `plan acceptance-check`, `task compile`,
`adapter validate`, `adapter inspect`, `adapter install-plan`, `adapter event-check`, `adapter
scaffold`, and `neutrality`. Adapter scaffold is template-only and can only
create `EXPERIMENTAL` projection skeletons. Adapter inspect records descriptor
and safe host capability discovery without live model invocation. Runtime
adapter execution and conformance lifecycle groups remain reserved and fail
closed with a stable `agent-lifecycle-error.v1` response until their runtime
core modules land.

`diagnose` builds a single redacted `agent-readiness-report.v1` view over the
checkout, package metadata, profiles, adapters and evidence availability. It is
read-only by default, includes dry-run install plans unless disabled, and never
changes maturity labels or creates a `VERIFIED` claim.

`context check` and `context render` also fail closed on overflow: if the
rendered receipt status is `FAIL`, the CLI exits non-zero and returns
`agent-lifecycle-error.v1` with code `context-overflow`. The receipt checks the
rendered envelope, reserved-output budget, active packet, state summary,
accepted evidence summary, optional `toolOutputs`, and recent verbatim
user-turn count.

`workflow finalize` requires `--final-audit`. The audit must pass with
`READY_FOR_FINALIZATION`, match the run's plan revision and digest, avoid
production-promotion claims, contain no unresolved MEDIUM+ findings, and carry
a valid `agent-completion-signal.v1` with `PASS` status or an explicit
evidence-bound `WAIVED` signal. If the adopted specification declares
`completionCheck`, finalization also requires the configured
`agent-completion-check-receipt.v1` to bind the same run, plan digest, source
revision, evidence ids and verifier before final proof can be written.
If `--goal-record` is supplied, that `agent-goal-record.v1` must be current for
the same lifecycle lineage and completion check before final proof can be
written.

`workflow task-accept` rechecks changed files from the committed task result
against the frozen task write scope and root write policy before accepting an
independent review. Forbidden, read-only or unowned paths fail closed with
`task-ownership-violation`.

Each task attempt records its own base revision at launch. A task result whose
`changeSet.baselineSha` differs from that attempt base is rejected unless it
contains a valid `agent-baseline-reconciliation-receipt.v1`.

Human-only work should be represented as workflow state, not prose completion.
Core transitions can park a run in `WAITING_FOR_EXTERNAL_ACTION` and resume it
only from a matching `agent-external-action-receipt.v1`. A human-decision
`completionCheck` must reference that existing external-action receipt instead
of inventing a second approval path.

Workflow transitions enforce task `controllerGates` for `pre-launch`,
`post-attempt`, `pre-acceptance`, and `finalization` phases. Expected receipts
are resolved from the frozen `receiptPath` template and must bind gate, run,
package, task, attempt, phase, operation, plan digest, source revision, PASS
verdict, freshness, dependencies, and configured attestation fields.

Tests use only the Python standard library:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
```

### Codex

Install from a tagged source marketplace:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref vX.Y.Z
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
```

You can also browse configured marketplaces with `/plugins`. Start a new Codex
session after installation so the bundled skills are loaded.

For public Plugins Directory publication, submit the root package as a
skills-only plugin through the OpenAI plugin submission portal. Codex CLI is
verified only for the tested 0.145.0 host range in the current source tree; do
not claim public directory approval or broader Codex host support until the
external review and matching evidence exist.

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

Claude Code is verified for the tested 2.1.220 host range in the current source
tree. The claim is backed by release-0-5 live conformance, live
calibration, and ALK lifecycle final proof listed in the support matrix.

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

The Cursor projection is still `EXPERIMENTAL`; local installation is useful for
validation and review, not for claiming verified runtime support.

### Gemini CLI

Gemini CLI currently uses a host-local source projection. Install the core from
a tagged checkout, then validate and inspect the projection:

```bash
git clone --branch vX.Y.Z https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python -m pip install -e .
gemini --version
agent-lifecycle adapter validate --descriptor adapters/gemini-cli/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/gemini-cli/adapter.descriptor.json
```

There is no published Gemini CLI runtime package in the current source tree.
The source tree includes `adapters/gemini-cli/runner.py` and
`tools/live_hosts/gemini_cli_harness.py` for bounded receipt normalization, but
Gemini CLI remains `EXPERIMENTAL` until live conformance, calibration and
lifecycle proof receipts are accepted. On the current local host, Gemini CLI
0.46.0 returns an unsupported Gemini Code Assist individual-client tier error,
so promotion cannot proceed without a supported Gemini/Antigravity setup.

### Hermes

Hermes can install the shared skills directly. To install all lifecycle skills
from the tagged release:

```bash
for skill in agent-first-planning audit-agent-plan agent-plan-to-workers agent-workflow-orchestrator audit-plan-implementation; do
  hermes skills install "https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/vX.Y.Z/skills/${skill}/SKILL.md"
done
```

The root `skills.sh.json` provides tap/category metadata for hosts that read
skills.sh-compatible indexes. `adapters/hermes/*` contains experimental
registry and slash-command projection metadata. It is not a live Hermes plugin
verification claim.

### Kimi Code

Kimi Code currently uses a host-local source projection. Make sure the `kimi`
CLI is available on `PATH`, then validate and inspect the projection:

```bash
git clone --branch vX.Y.Z https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python -m pip install -e .
kimi --version
agent-lifecycle adapter validate --descriptor adapters/kimi-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/kimi-code/adapter.descriptor.json
```

There is no published Kimi Code runtime package in the current source tree. The
source tree includes `adapters/kimi-code/runner.py` and
`tools/live_hosts/kimi_code_harness.py` for bounded receipt normalization, but
Kimi Code remains `EXPERIMENTAL` until live conformance, calibration and
lifecycle proof receipts are accepted. On the current local host, `kimi
provider list` reports no configured providers, so promotion cannot proceed
until a provider/model alias is configured outside the portable ALK core.

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
claimed by the current source tree.

### qwen-code

qwen-code currently uses a host-local source projection. Install the core from
a tagged checkout, then validate and inspect the projection. The current source
tree is `VERIFIED` for qwen-code `0.21.0`.

```bash
git clone --branch vX.Y.Z https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python -m pip install -e .
qwen --version
agent-lifecycle adapter validate --descriptor adapters/qwen-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/qwen-code/adapter.descriptor.json
```

The live runner is `adapters/qwen-code/runner.py`; the release harness is
`tools/live_hosts/qwen_code_harness.py`. No public qwen-code adapter package,
public directory approval, or production-promotion platform claim is published
for the current source tree.

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
- Gemini CLI: use the source projection for validation only until live runtime
  support is promoted
- Hermes: run `/agent-workflow-orchestrator` after installing the skill; the
  current tree is `VERIFIED` for Hermes Agent v0.19.0
- Kimi Code: use the source projection for validation only until live runtime
  support is promoted
- OpenCode: ask the agent to load `agent-workflow-orchestrator` through its
  native skill tool; the current tree is `VERIFIED` for OpenCode CLI 1.18.9
- qwen-code: use the source projection with qwen-code `0.21.0`; the current
  tree is `VERIFIED` for host-local GLM 5.2 live receipts

The release support matrix is authoritative for exact namespaced syntax and
host maturity. An `EXPERIMENTAL` adapter projection is not a live runtime
compatibility claim.

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

For model-backed attempts, adapters must execute the task with the selected
`attemptModelRoute` or fail closed. The controller accepts the result only when
the usage receipt binds to the run, task, attempt, plan digest, source revision
and route decision digest.

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
- [Readiness diagnostics](docs/reference/readiness-diagnostics.md)
- [Completion check](docs/reference/completion-check.md)
- [Adapter live-promotion runbook](docs/adapters/live-promotion-runbook.md)
- [Verified-adapter release checklist](docs/guides/verified-adapter-release-checklist.md)
- [Modular controller architecture](docs/architecture/modular-controller.md)
- [Codex plugin documentation](https://learn.chatgpt.com/docs/build-plugins)
- [Claude Code plugin documentation](https://code.claude.com/docs/en/plugins)
- [Cursor plugin documentation](https://cursor.com/docs/plugins)
- [Hermes skills documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [OpenCode skills](https://opencode.ai/docs/skills/)
- [OpenCode plugins](https://opencode.ai/docs/plugins/)

## License

Licensed under the [Apache License 2.0](LICENSE).
