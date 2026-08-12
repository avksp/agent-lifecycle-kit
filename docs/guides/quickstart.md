# Quickstart

This guide shows the smallest useful source-checkout flow. It starts with local
checks and then points to the explicit adapter routes for host work.

For the project structure, read
[System architecture](../architecture/system-architecture.md). For how ALK
differs from coding agents, runtimes, specification tools and memory systems,
read [Project comparison](../reference/project-comparison.md).
For the complete path through research, planning, review, implementation and
resume, see [How ALK works for different tasks](how-alk-works.md).
For the boundaries of multi-agent work, workflow customization, model selection,
timeouts and retries, see [Workflow customization and execution
controls](../reference/workflow-customization.md).

## Install from source

```bash
python -m pip install -e .
agent-lifecycle version
```

Without installation, run from the checkout:

```bash
PYTHONPATH=src python -m agent_lifecycle version
```

## Install from package

The official [PyPI project](https://pypi.org/project/agent-lifecycle-kit/)
supports Python 3.11-3.14. When the package is available for the requested
version, install the exact semantic version:

```bash
python -m pip install agent-lifecycle-kit==1.63.1
agent-lifecycle version
```

If a requested version has not been published to PyPI, use the source checkout
path above. A Git tag alone is not enough for plugin installation; plugin
manifests inside the tag must also carry the same version. See
[Plugin publication](../reference/plugin-publication.md).

## Check readiness

```bash
agent-lifecycle diagnose --no-install-plans
```

The report is redacted. It validates package metadata, profiles, adapter
descriptors, safe adapter inspection state, tracked evidence summaries, and
declared local raw receipt availability. Live execution uses an explicit adapter
route described below.

For one adapter:

```bash
agent-lifecycle diagnose \
  --adapter adapters/<adapter-id>/adapter.descriptor.json \
  --no-install-plans
```

## Preview adapter setup

```bash
agent-lifecycle adapter install-plan \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json
```

The output is a dry run. It projects validated installation facts from the
adapter descriptor as files, argv arrays and operator actions. Review the plan,
then apply the listed operator actions when configuring the host.

## Run a plan gate

For a frozen plan:

```bash
agent-lifecycle plan check \
  --manifest path/to/plan.manifest.json \
  --lock path/to/plan.lock.json
```

The plan remains the source of truth for ownership, write scope, acceptance,
validation, and evidence expectations.

## Import planning files

To review an external planning file before turning it into an ALK plan:

```bash
agent-lifecycle import plan \
  --source specs/checkout.md \
  --dialect openspec \
  --out work/imports/checkout-import.json
```

To review a folder with several Markdown files:

```bash
agent-lifecycle import plan \
  --source specs/checkout/ \
  --dialect spec-kit \
  --out work/imports/checkout-folder-import.json
```

The same command supports `--dialect bmad` and `--dialect spec-kitty`.
Imported material enters the draft stage. Review and freeze it before using it as
the implementation plan.

## Use a project workflow profile

For a project-wide default adapter and bounded stage settings, create the local
profile once:

```bash
agent-lifecycle project profile init --adapter <adapter-id> --out .alk/project-profile.json
agent-lifecycle project profile check
```

The optional `--adapter` value becomes the project default. Without it, set
`defaultAdapter` in the local file or keep passing `--adapter` for each run.
After a default is set, the simple entrypoint can omit `--adapter`:

```bash
agent-lifecycle start --file task.md
agent-lifecycle start --text "Investigate the cache failure"
```

The profile is a local defaults layer. A frozen plan and its lock remain the
authority for risk, quality, write scope and required evidence. Use
[Project workflow profile](../reference/project-workflow-profile.md) for the
file format, explicit selection and the advanced `--no-project-profile` route.

## Choose how to use an adapter

Choose `<adapter-id>` from the [linked adapter
table](../adapters/usage-modes.md). The detailed limits for several agents,
custom plan stages, host model settings, prompts, timeouts and retries are in
[Workflow customization and execution controls](../reference/workflow-customization.md).
There are two normal entrypoints:

- Inside a host whose adapter page documents a plugin or shared-skill route,
  open the target project and send the request below. The host runs the model
  and tools.
- From the project terminal, run `agent-lifecycle start --adapter <adapter-id>`.
  ALK reads the task and creates a receipt. Add a qualified `--launch` route when
  the operator wants one bound host process.

```text
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle: clarify the request, create and independently
review the plan, freeze it before implementation, audit implementation results,
and finish only with accepted evidence and final proof.
Task: <describe the task or name the Markdown file to read>
```

This wording tells the in-session agent to use the complete ALK process rather
than treating the skill as background guidance. The adapter page explains how
that host loads or invokes the skill. For adapters without an in-session route,
use the terminal command.

The plugin or skill supplies the host-side workflow guidance. Managed proof is
recorded by ALK state transitions, reviews, audits and accepted receipts. Exact
installation and invocation instructions for all twelve bundled adapters are in [Using ALK with an
adapter](../adapters/usage-modes.md).

## Start with one command

For a task file or short text:

```bash
agent-lifecycle start --adapter <adapter-id> --file task.md
agent-lifecycle start --adapter <adapter-id> --text "Fix the failing test"
```

The default mode is `auto`. Raw input creates
`agent-lifecycle-start-receipt.v1` with a review-gated draft result. Use an
explicit preparation mode when the requested outcome is narrower:

```bash
agent-lifecycle start --adapter <adapter-id> --mode research --file research.md
agent-lifecycle start --adapter <adapter-id> --mode plan --file feature.md
agent-lifecycle start --adapter <adapter-id> --mode review --file proposed-plan.md
```

To request one external CLI process for planning, add `--launch`:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode plan \
  --file feature.md \
  --launch
```

This route uses an exact-version profile with planning status
`PLANNING_ONLY_QUALIFIED`. The current planning matrix lists the profile state
for every bundled adapter and the preparation commands for qualification. See
[Planning-only adapter launch](../reference/planning-only-launch.md).

Only `--mode implement` can delegate to the existing managed-run path, and it
requires a structured frozen run request with complete state, manifest, lock,
task, operation and revision bindings:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode implement \
  --file work/run/adapter-run-request.json
```

For a frozen task, add `--risk auto` to derive a provider-neutral model route
and resource caps. The read-only start step writes the exact profile with
`--risk-profile-out`; authorize it separately with `workflow task-start
--risk-profile`. See [Risk-aware execution](../reference/risk-aware-execution.md)
for the complete sequence. On raw text or Markdown, `--risk` records a
recommendation; implementation authorization comes from the frozen workflow
binding.

The start receipt also contains a compact `executionStrategy`. Raw intake says
`DEFERRED_UNTIL_FREEZE`; a completely bound frozen run reports the quality
floor, neutral implementation class, packet mode, review mode and resource
caps. Advanced users can write the full strategy with `strategy resolve` and
pass it to `task compile --strategy`. See [Quality-preserving execution
strategy](../reference/execution-strategy.md).

To resume an ordinary managed session recorded by ALK:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --resume <session-id> \
  --session-root .alk/adapter-sessions
```

Resume verifies the stored adapter and workflow lineage. The id refers to the
ALK-managed session associated with that workflow.
For a planning-session id returned by `start --launch`, omit `--session-root`:

```bash
agent-lifecycle start --adapter <adapter-id> --resume <planning-session-id>
```

This reads digest-only `.alk/planning-sessions` state. Advanced operators can
generate and preflight an exact-version declaration for any bundled adapter; use
the documented frozen-task profiles when accepted launch evidence is required.
For a qualified adapter, substitute the exact ids and paths from the
[qualified host launch guide](../reference/qualified-host-launch.md):

```bash
agent-lifecycle adapter launch-profile \
  --adapter <qualified-adapter-id> \
  --repository-root /path/to/agent-lifecycle-kit \
  --out .alk/host-launch/<qualified-adapter-id>.json
agent-lifecycle host-launch preflight \
  --profile .alk/host-launch/<qualified-adapter-id>.json
```

Then launch one local host command only from a frozen, risk-bound `implement`
run:

```bash
agent-lifecycle start \
  --adapter <qualified-adapter-id> \
  --mode implement \
  --file work/run/adapter-run-request.json \
  --risk auto \
  --host-model-profile <host-model-profile.json> \
  --launch \
  --host-launch-profile .alk/host-launch/<qualified-adapter-id>.json
```

Create and inspect the ignored profile first. The [local host launch
guide](../reference/local-host-launch.md) describes the format, preflight and
fail-closed boundaries. The lower-level `adapter task start`, `adapter run` and
`adapter session resume` commands remain available in the [CLI
reference](../reference/cli.md).
The [qualified host launch guide](../reference/qualified-host-launch.md)
describes the distinct frozen implementation route and its S1/S2 usage
boundary. Planning uses the dedicated planning-launch workflow above.

## Review code changes

For a local branch, GitHub pull request or GitLab merge request, first prepare a
diff and a short review task:

```bash
mkdir -p work/code-review/current
git diff origin/main...HEAD > work/code-review/current/diff.patch
```

Then pass the task to ALK without starting implementation:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode review \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/start.json

agent-lifecycle review-mesh recommend \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/recommendation.json
```

Use this for ordinary diff review, architecture review, security review and
pre-merge risk review. Full GitHub, GitLab, architecture and implementation
audit examples are in [Code review workflows](code-review-workflows.md).

## Optional review with several AI models

For research, planning or audit-heavy work, the same artifact can be checked by
independent adapter/model bindings, for example Codex, Claude Code and
OpenCode/GLM. Ask for a local Review Mesh recommendation before putting this
requirement into a plan:

```bash
agent-lifecycle review-mesh recommend --file task.md
```

To prepare local reviewer packets from a task intake receipt:

```bash
agent-lifecycle adapter task start \
  --adapter <adapter-id> \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/intake.json

agent-lifecycle review-mesh prepare \
  --intake work/code-review/current/intake.json \
  --template leader-draft-review \
  --reviewer reviewer-a:plan-reviewer:strong-reasoning \
  --reviewer reviewer-b:risk-reviewer:strong-reasoning \
  --reviewer reviewer-c:independent-reviewer:local-strong-review \
  --out-dir work/code-review/current/review-mesh \
  --out work/code-review/current/review-mesh-prepare.json
```

The selected CLI executes each generated assignment, then ALK imports its
structured answer. If a reviewed frozen plan opts in, use `review-mesh prepare`
or the atomic
`assign`, `import-result`, `synthesize` and `quorum` commands to coordinate
reviewer evidence through the selected adapters. See the
[multi-model review workflow](review-mesh-workflow.md) for common task cases.
Any available adapter/model combination may be used. Review Mesh is optional
and `off` by default. If only one model is available, continue with the normal
single-reviewer lifecycle unless a frozen plan explicitly requires quorum.
For cookbook recipes that stop at research, planning, Markdown review or
implementation audit, see [Lifecycle cookbook](lifecycle-cookbook.md).

## Keep context small

Use the compact profile before handing work to a constrained model:

```bash
agent-lifecycle context check \
  --profile profiles/small-context-profile.v1.json
```

The profile keeps summaries short and explicit while preserving the gates that
protect final quality.

## View goal and progress

When a run already has a goal record and workflow state, use one read-only view
to inspect the current outcome, lifecycle phase, elapsed time, token usage and
code-change counters:

```bash
agent-lifecycle goal view \
  --record work/run/goal.json \
  --state work/run/state.json \
  --usage-receipt work/run/usage.json \
  --change-summary work/run/change-summary.json \
  --terminal
```

The command only reads existing artifacts. It is safe to run in a second
terminal while another adapter is working.

## Compare process changes locally

Run the bundled deterministic suite without a model account or external CLI:

```bash
mkdir -p work
cp tests/benchmarks/fixtures/accepted-pass.json work/benchmark-submission.json
agent-lifecycle benchmark evaluate \
  --suite benchmarks/reference-tasks/manifest.json \
  --artifact work/benchmark-submission.json \
  --out work/benchmark-evaluation.json
```

The receipt reports oracle results, false acceptances, retries, elapsed time,
and confidence-labeled token buckets. See the [reference task evaluation
guide](reference-task-evaluation.md) before comparing runs.

## Check release neutrality

Use the Git-index-bound scope for a portable source or release check:

```bash
agent-lifecycle-neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --require-zero-findings
```

Ignored evidence under approved policy roots is not read unless a dedicated
job adds `--include-local-artifacts`. See
[Neutrality scanning](../reference/neutrality.md) before enabling it.

## What next

- [Adapter installation](../adapters/install.md)
- [Code review workflows](code-review-workflows.md)
- [Lifecycle cookbook](lifecycle-cookbook.md)
- [CLI reference](../reference/cli.md)
- [Readiness diagnostics](../reference/readiness-diagnostics.md)
- [Neutrality scanning](../reference/neutrality.md)
