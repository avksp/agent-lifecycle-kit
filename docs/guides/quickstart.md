# Quickstart

This guide shows the smallest useful source-checkout flow. It performs no live
model calls and does not write host configuration.

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

When the package is available for the release, install the exact semver version:

```bash
python -m pip install agent-lifecycle-kit==1.45.0
agent-lifecycle version
```

If the package is not available yet, use the source checkout path above. A Git
tag alone is not enough for plugin installation; plugin manifests inside the
tag must also carry the same version. See
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

The output is a dry run. It lists files, commands, and operator actions, but it
does not mutate the host and does not change adapter maturity.

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

If a reviewed frozen plan opts in, use `review-mesh assign`,
`import-result`, `synthesize` and `quorum` to coordinate reviewer evidence
without launching reviewer hosts from ALK core. See the
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
