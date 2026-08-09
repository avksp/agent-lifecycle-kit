# Quickstart

This guide shows the smallest useful source-checkout flow. It performs no live
model calls and does not write host configuration.

For the project structure, read
[System architecture](../architecture/system-architecture.md). For how ALK
differs from coding agents, runtimes, specification tools and memory systems,
read [Project comparison](../reference/project-comparison.md).

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
python -m pip install agent-lifecycle-kit==1.51.0
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
declared local raw receipt availability. It does not start live calls.

For one adapter:

```bash
agent-lifecycle diagnose \
  --adapter adapters/codex/adapter.descriptor.json \
  --no-install-plans
```

## Preview adapter setup

```bash
agent-lifecycle adapter install-plan \
  --descriptor adapters/opencode/adapter.descriptor.json
```

The output is a dry run. It projects validated installation facts from the
adapter descriptor as files, argv arrays and operator actions. It does not
execute the arrays, mutate the host or change adapter maturity.

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
Imported material remains a draft candidate. It cannot start implementation or
replace a frozen ALK plan until it is reviewed and frozen.

## Start adapter task intake

For a task file or short text:

```bash
agent-lifecycle adapter task start --adapter codex --file task.md
agent-lifecycle adapter task start --adapter codex --text "Fix the failing test"
```

This does not start implementation for raw input. It returns a review-gated
draft receipt. Managed execution requires a frozen run request or a frozen plan
with workflow binding.

## Review code changes

For a local branch, GitHub pull request or GitLab merge request, first prepare a
diff and a short review task:

```bash
mkdir -p work/code-review/current
git diff origin/main...HEAD > work/code-review/current/diff.patch
```

Then pass the task to ALK without starting implementation:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/intake.json

agent-lifecycle review-mesh recommend \
  --intake work/code-review/current/intake.json \
  --out work/code-review/current/recommendation.json
```

Use this for ordinary diff review, architecture review, security review and
pre-merge risk review. Full GitHub, GitLab, architecture and implementation
audit examples are in [Code review workflows](code-review-workflows.md).

## Optional multi-review advice

For research, planning or audit-heavy work, ask for a local Review Mesh
recommendation before putting it into a plan:

```bash
agent-lifecycle review-mesh recommend --file task.md
```

To prepare local reviewer packets from a task intake receipt:

```bash
agent-lifecycle review-mesh prepare \
  --intake work/code-review/current/intake.json \
  --template leader-draft-review \
  --reviewer codex-example:plan-reviewer:strong-reasoning \
  --reviewer claude-example:risk-reviewer:strong-reasoning \
  --out-dir work/code-review/current/review-mesh \
  --out work/code-review/current/review-mesh-prepare.json
```

If a reviewed frozen plan opts in, use `review-mesh prepare` or the atomic
`assign`, `import-result`, `synthesize` and `quorum` commands to coordinate
reviewer evidence without launching reviewer hosts from ALK core. See the
[Review Mesh workflow cookbook](review-mesh-workflow.md) for common task cases.
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
