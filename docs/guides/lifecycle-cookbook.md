# Lifecycle cookbook

Use this cookbook when you know the kind of work you want, but do not want to
assemble the lower-level ALK commands from scratch. Every recipe keeps raw
input draft-only until a reviewed plan or run request explicitly authorizes
execution.

## Choose a recipe

| Need | Start here | Stops before implementation |
| --- | --- | --- |
| Research an area and write a plan | [Research and planning only](#research-and-planning-only) | Yes |
| Review one task file | [Review one Markdown task](#review-one-markdown-task) | Yes |
| Review several Markdown plan files | [Review a Markdown plan folder](#review-a-markdown-plan-folder) | Yes |
| Review code or a PR/MR | [Review code changes](#review-code-changes) | Yes |
| Audit completed ALK work | [Audit implementation evidence](#audit-implementation-evidence) | No, it audits completed work |
| Ask several reviewers | [Coordinate cross-review](#coordinate-cross-review) | Yes, unless a frozen plan requires quorum |
| Inspect an active run | [View goal and progress](#view-goal-and-progress) | Yes |

## Research and planning only

Use this when the deliverable is analysis, architecture notes or a plan.

```bash
cat > work/tasks/research.md <<'EOF'
# Task

Research the current adapter session flow and write an implementation plan.
Do not change code.

Return:
- architecture observations;
- risks and open questions;
- recommended ALK plan shape;
- validation commands that would be needed later.
EOF

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/tasks/research.md \
  --out work/tasks/research-intake.json

agent-lifecycle review-mesh recommend \
  --intake work/tasks/research-intake.json \
  --out work/tasks/research-recommendation.json
```

Stop here if you only need research. To implement later, turn the accepted plan
into a normal ALK plan package and freeze it.

## Review one Markdown task

Use this for a task, proposal or plan saved in one file:

```bash
agent-lifecycle adapter task start \
  --adapter claude \
  --file tasks/proposal.md \
  --out work/review/proposal-intake.json

agent-lifecycle review-mesh recommend \
  --intake work/review/proposal-intake.json \
  --out work/review/proposal-recommendation.json
```

The adapter id selects the host-local context for the intake receipt. It does
not start the host or model for raw Markdown.

## Review a Markdown plan folder

Use the import command when the plan is split across several Markdown files:

```bash
agent-lifecycle import plan \
  --source tasks/release-1-40/ \
  --dialect spec-kit \
  --out work/review/plan-import.json
```

For reviewer-facing intake, create one task that points at the folder or at the
import receipt:

```bash
cat > work/review/plan-review-task.md <<'EOF'
# Task

Review the Markdown plan package represented by work/review/plan-import.json.
Do not implement.

Check requirements, acceptance criteria, evidence routes, write ownership,
security gates and release claims.
EOF

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/review/plan-review-task.md \
  --out work/review/plan-review-intake.json
```

## Review code changes

Prepare a diff with Git, GitHub CLI or GitLab refspecs, then pass one explicit
review task to ALK:

```bash
mkdir -p work/code-review/current
git diff origin/main...HEAD > work/code-review/current/diff.patch
```

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/intake.json
```

When architecture is documented, list the architecture documents in the task
file. When it is not documented, ask the reviewer to recover module
responsibilities first, then review the diff against that recovered map.

Full examples are in [Code review workflows](code-review-workflows.md).

## Audit implementation evidence

Use implementation audit after a worker has produced a task result and review:

```bash
agent-lifecycle audit implementation \
  --manifest tasks/release-x/plan.manifest.json \
  --state work/run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

Add `--review-mesh-quorum <path>` only when the frozen plan requires a quorum
receipt for that phase.

## View goal and progress

Use this when another adapter is working and you need a compact, read-only
status line:

```bash
agent-lifecycle goal view \
  --record work/run/goal.json \
  --state work/run/state.json \
  --usage-receipt work/run/usage.json \
  --change-summary work/run/change-summary.json \
  --terminal
```

The command does not claim completion. It only combines the goal record,
workflow state, progress rows, token receipts and Git-style change summary.

## Coordinate cross-review

For higher-risk research, planning or audits, create reviewer assignments with
`review-mesh assign`, run the reviewers outside ALK, import their JSON output,
then synthesize and check quorum.

See [Review Mesh workflow cookbook](review-mesh-workflow.md) for concrete
Codex, Claude and OpenCode/GLM examples. GLM is only an example model behind
OpenCode; any configured model can be used by changing the host command.

## Safety rules

- Do not put secrets or private environment values in task files.
- Prefer relative repository paths in portable packets.
- Treat `review-mesh recommend` as advice until a frozen plan opts in.
- Plugin installation alone is not proof that the ALK lifecycle ran.
- Raw text, Markdown and imported plans never authorize implementation by
  themselves.
