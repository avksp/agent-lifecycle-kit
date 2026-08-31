# Commands by task

Use this page after the [first run](install-and-first-run.md). The examples use
`<adapter-id>` so the same route works with any bundled adapter. The adapter
page defines the host-specific command and model settings.

## Check the environment

```
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
agent-lifecycle adapter validate --descriptor adapters/<adapter-id>/adapter.descriptor.json
agent-lifecycle adapter inspect --descriptor adapters/<adapter-id>/adapter.descriptor.json
```

Use `version` to check the active installation and `diagnose` to check the
repository-facing environment. Adapter validation reads the descriptor and
inspection reports its declared capabilities without starting the host.

Preview host setup without applying any operator action:

```
agent-lifecycle adapter install-plan \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json
```

## Prepare a task

Use a Markdown file when the request is long, contains acceptance criteria, or
refers to several documents:

```
agent-lifecycle start --adapter <adapter-id> --file task.md
agent-lifecycle start --adapter <adapter-id> --text "Investigate the cache failure"
```

Select the intended preparation mode when the result is known:

```
agent-lifecycle start --adapter <adapter-id> --mode research --file research.md
agent-lifecycle start --adapter <adapter-id> --mode plan --file feature.md
agent-lifecycle start --adapter <adapter-id> --mode review --file proposed-plan.md
```

To import an existing specification or plan folder into a reviewable draft:

```
agent-lifecycle import plan \
  --source specs/checkout/ \
  --dialect openspec \
  --out work/imports/checkout.json
```

Supported dialects include `openspec`, `spec-kit`, `bmad` and
`spec-kitty`. The import is context for a new ALK plan; it does not authorize
implementation.

## Check a plan

Run all required plan checks before freeze:

```
agent-lifecycle plan check \
  --manifest tasks/release-<version>/plan.manifest.json \
  --lock tasks/release-<version>/plan.lock.json
agent-lifecycle plan acceptance-check \
  --manifest tasks/release-<version>/plan.manifest.json
agent-lifecycle plan refs-check \
  --manifest tasks/release-<version>/plan.manifest.json
agent-lifecycle plan completeness-check \
  --manifest tasks/release-<version>/plan.manifest.json
```

The frozen manifest and lock bind requirements, ownership, allowed writes,
acceptance criteria, validation commands and evidence routes. An independent
plan audit is the decision point before implementation.

## Implement a frozen task

A raw task first becomes a reviewed specification and plan. Implementation uses
a structured frozen run request:

When the exact next transition is not known, use `workflow continue` in two
steps: project without `--apply`, then repeat the same inputs with `--apply`,
the projected revision and action digest. Direct transition commands remain
available. See [Workflow continuation](../reference/workflow-continuation.md).
When several deterministic transitions are already declared, bounded mode can
apply their explicit bundle in one invocation. It requires
`--until-blocked --apply`, a lock, positive transition/I/O caps and a dedicated output receipt;
it stops before external authority or evidence is required.

```
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode implement \
  --file work/run/adapter-run-request.json
```

For risk-aware execution, derive a profile before authorization:

```
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode implement \
  --risk auto \
  --risk-profile-out work/risk-profile.json \
  --file work/run/adapter-run-request.json

agent-lifecycle workflow task-start \
  --risk-profile work/risk-profile.json
```

The profile selects a provider-neutral model route, token and time limits, and
usage receipts for the declared risk level. It does not select a provider for
the host or bypass the frozen plan.

Resume an ALK-managed session with its stored lineage:

```
agent-lifecycle start \
  --adapter <adapter-id> \
  --resume <session-id> \
  --session-root .alk/adapter-sessions
```

## Review a change

For a local diff:

```
git diff --stat
git diff -- src/ tests/
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode review \
  --file review-request.md
```

For a plan and its implementation package:

```
agent-lifecycle audit package \
  --plan-dir tasks/release-<version> \
  --state work/state.json \
  --base main \
  --require-frozen \
  --require-implementation \
  --strict \
  --out work/evidence/implementation-audit.json
```

For a GitHub or GitLab change, export the reviewable diff and changed-file
metadata in the project checkout, then pass the review request and evidence
paths to the same route. The remote service remains the source of the merge
request or pull request; ALK checks the declared plan and evidence.

## Review with several AI models

Review Mesh is optional and disabled by default. It can use any combination of
available adapters and models; there is no required provider pair. If only one
model is available, use the ordinary review route.

```
agent-lifecycle review-mesh recommend \
  --file review-request.md \
  --out work/review-mesh/recommendation.json

agent-lifecycle review-mesh profile \
  --profile-id rm-review \
  --default-mode parallel-research-synthesis \
  --reviewer-model-class strong-reasoning \
  --reviewer-model-class local-strong-review \
  --out work/review-mesh/profile.json

agent-lifecycle review-mesh prepare \
  --intake work/review-mesh/intake.json \
  --template parallel-research-synthesis \
  --profile-id rm-review \
  --phase plan-review \
  --reviewer reviewer-a \
  --reviewer reviewer-b \
  --out-dir work/review-mesh/assignments \
  --out work/review-mesh/prepare.json

agent-lifecycle review-mesh assign \
  --intake work/review-mesh/intake.json \
  --profile work/review-mesh/profile.json \
  --mode parallel-research-synthesis \
  --phase plan-review \
  --assignment-id RM-1 \
  --reviewer-id reviewer-a \
  --out work/review-mesh/assignment-a.json
agent-lifecycle review-mesh import-result \
  --profile work/review-mesh/profile.json \
  --assignment work/review-mesh/assignment-a.json \
  --reviewer-output work/review-mesh/reviewer-a.json \
  --out work/review-mesh/result-a.json
agent-lifecycle review-mesh synthesize \
  --profile work/review-mesh/profile.json \
  --result work/review-mesh/result-a.json \
  --result work/review-mesh/result-b.json \
  --out work/review-mesh/synthesis.json
agent-lifecycle review-mesh quorum \
  --profile work/review-mesh/profile.json \
  --synthesis work/review-mesh/synthesis.json \
  --min-reviewers 2 \
  --out work/review-mesh/quorum.json
  --synthesis work/review-mesh/synthesis.json
```

The adapters run the selected hosts and models. ALK stores neutral identities,
budgets, findings, redaction status and quorum evidence.

## Use project defaults

```
agent-lifecycle project profile init \
  --adapter <adapter-id> \
  --out .alk/project-profile.json
agent-lifecycle project profile check
```

The profile stores local defaults. The frozen plan remains authoritative for
risk, write scope, required reviews and acceptance.

## Inspect progress and context

```
agent-lifecycle report progress --state work/state.json --terminal
agent-lifecycle report progress --state work/state.json --watch --terminal
agent-lifecycle report status-view --state work/state.json
agent-lifecycle context check --state work/state.json
agent-lifecycle goal check --state work/state.json
agent-lifecycle goal summarize --state work/state.json
```

These commands are read-only projections. They do not call a model.

For a long session, save and restore a bounded continuity packet explicitly:

```
agent-lifecycle context checkpoint \
  --session session-123 \
  --state work/run.state.json \
  --plan tasks/current/plan.manifest.json \
  --input work/context/decisions.json \
  --reason agent-requested \
  --out .alk/context/checkpoints/session-123.json

agent-lifecycle context restore \
  --checkpoint .alk/context/checkpoints/session-123.json \
  --state work/run.state.json \
  --session session-123 \
  --out work/context/continuation.json
```

Restore returns a bounded continuation receipt after lineage and redaction
checks. It does not replace the frozen plan or authorize implementation.

## Validate release and security evidence

```
agent-lifecycle-neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --require-zero-findings
agent-lifecycle-neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --include-local-artifacts \
  --require-zero-findings
python tools/release/validate_publication_versions.py \
  --target-version <version> \
  --target-ref v<version> \
  --evidence work/evidence/publication-versions.json
agent-lifecycle benchmark evaluate \
  --manifest benchmarks/reference-tasks/manifest.json \
  --out work/evaluation/reference-task-results.json
```

Use `--tracked-release` for publication evidence and
`--include-local-artifacts` when a local generated artifact is deliberately
part of the check.
