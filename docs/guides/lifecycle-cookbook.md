# Lifecycle task scenarios

## Canonical execution route

For implementation work, use `workflow continue` when the exact next transition
is not already known: project first, then explicitly apply the same action with
its revision and digest guards. Direct `workflow task-*` commands remain the
state transition surface for callers that already know the route. See
[Workflow continuation](../reference/workflow-continuation.md).
For a predeclared deterministic sequence, use its `--until-blocked --apply`
mode with an explicit bundle and positive transition/I/O caps; ALK still stops
before any model, host, reviewer, operator or plan-authority action. The legacy
`runner` commands are compatibility journals only; they are deprecated and
cannot authorize, accept or finalize work. A runner receipt must be treated as
evidence to attach to workflow state, never as a replacement for a workflow
transition.

Use these lifecycle task scenarios when you know the kind of work you want, but do not want to
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
| Continue after a review requests changes | [Open a remediation attempt](#open-a-remediation-attempt) | No, it continues a frozen task |
| Find or fix a bug | [Bug Forensics repair](#bug-forensics-repair) | No, after a frozen plan authorizes repair |
| Ask several reviewers | [Coordinate cross-review](#coordinate-cross-review) | Yes, unless a frozen plan requires quorum |
| Inspect an active run | [View goal and progress](#view-goal-and-progress) | Yes |
| Start a frozen task with bounded resources | [Run a risk-aware task](#run-a-risk-aware-task) | No, it authorizes one task attempt |

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

agent-lifecycle start \
  --adapter codex \
  --mode research \
  --file work/tasks/research.md \
  --out work/tasks/research-start.json

agent-lifecycle review-mesh recommend \
  --file work/tasks/research.md \
  --out work/tasks/research-recommendation.json
```

Stop here if you only need research. To implement later, turn the accepted plan
into a normal ALK plan package and freeze it.

## Review one Markdown task

Use this for a task, proposal or plan saved in one file:

```bash
agent-lifecycle start \
  --adapter claude \
  --mode review \
  --file tasks/proposal.md \
  --out work/review/proposal-start.json

agent-lifecycle review-mesh recommend \
  --file tasks/proposal.md \
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

agent-lifecycle start \
  --adapter codex \
  --mode review \
  --file work/review/plan-review-task.md \
  --out work/review/plan-review-start.json
```

## Review code changes

Prepare a diff with Git, GitHub CLI or GitLab refspecs, then pass one explicit
review task to ALK:

```bash
mkdir -p work/code-review/current
git diff origin/main...HEAD > work/code-review/current/diff.patch
```

```bash
agent-lifecycle start \
  --adapter codex \
  --mode review \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/start.json
```

When architecture is documented, list the architecture documents in the task
file. When it is not documented, ask the reviewer to recover module
responsibilities first, then review the diff against that recovered map.

Full examples are in [Code review workflows](code-review-workflows.md).

## Run a risk-aware task

Use this only after the plan is reviewed and frozen. First project the exact
profile without mutating workflow state:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode implement \
  --risk auto \
  --file tasks/my-release/plan.manifest.json \
  --state work/my-release/run.state.json \
  --lock tasks/my-release/plan.lock.json \
  --task WS-01 \
  --operation-id start-WS-01-attempt-1 \
  --expected-revision 3 \
  --source-revision "$(git rev-parse HEAD)" \
  --host-model-profile profiles/hosts/codex-live-profile.v1.json \
  --risk-profile-out work/my-release/WS-01/risk-profile.json
```

Then authorize the attempt with the same operation id:

```bash
agent-lifecycle workflow task-start \
  --state work/my-release/run.state.json \
  --task WS-01 \
  --operation-id start-WS-01-attempt-1 \
  --expected-revision 3 \
  --source-revision "$(git rev-parse HEAD)" \
  --risk-profile work/my-release/WS-01/risk-profile.json \
  --reason "start risk-aware attempt"
```

The host must later attest tokens, invocation count and wall time. Any missing,
estimated, lineage-drifted or over-cap value blocks the result transition. See
[Risk-aware execution](../reference/risk-aware-execution.md) for all inputs and
failure rules.

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

## Open a remediation attempt

Use this when an independent task review or implementation audit returns
`REWORK` for findings that remain inside the frozen task scope. The plan must
use `remediationMode: ask` or `bounded-auto` and set `maxTaskAttempts` to at
least 2.

Before submitting each task result, calculate the current Git-backed claim:

```bash
agent-lifecycle workflow task-snapshot \
  --state work/run.state.json \
  --task WS-01 \
  --out work/WS-01/attempt-1/task-snapshot.json
```

The worker places the returned `claim` object in the task result as
`changeSet`. After `task-result` and independent review, request rework with
the exact open finding IDs:

```bash
agent-lifecycle workflow task-rework \
  --state work/run.state.json \
  --task WS-01 \
  --operation-id rework-WS-01-attempt-1 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --review work/WS-01/attempt-1/task-review.json \
  --finding-id F-101 \
  --reason "address independent review findings"
```

Add `--implementation-audit <path>` when the plan requires implementation
audit or when that audit is the artifact that returned `REWORK`. The command
archives artifact identities, not duplicate bodies. `workflow run` then
returns the same task for another `task-start`, which opens the first unused
attempt path. Previous result, review and audit files remain immutable.

## Use the v4 task-local workflow

For a new run, create the validated v4 state before adopting task artifacts:

```bash
agent-lifecycle workflow init \
  --state work/run.state.json \
  --run-id run-001 \
  --package-id release-x
```

For a legacy v3 state, use the explicit migration command and keep the source
revision and expected state revision bound to the migration receipt:

```bash
agent-lifecycle workflow state-migrate \
  --state work/run.state.json \
  --operation-id migrate-run-001 \
  --expected-revision 1 \
  --source-revision <source-sha>
```

After a task result and independent review exist, apply the single canonical
task outcome. `ACCEPTED`, `REWORK`, `CONTRACT_CHANGE` and `BLOCKED` are
task-local outcomes; an active sibling keeps running and earlier attempt
artifacts remain immutable:

```bash
agent-lifecycle workflow task-review-apply \
  --state work/run.state.json \
  --task WS-01 \
  --operation-id review-WS-01-attempt-1 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json
```

The run enters `FINAL_AUDIT` only after every required task is accepted. The
legacy `task-accept` and `task-rework` commands remain compatibility wrappers
for one release and use the same transition service.

## Recover a run without editing state

Approval-required runs consume an exact-lineage receipt through
`workflow authorize`; `PLAN_ONLY` runs never become executable. Pause a
supported phase for one host-owned operation with `workflow external-pause`
and resume it with `workflow external-resume` only after the matching receipt
has been written. Typed blockers expose their legal route, so a generic
`resolve-blocker` cannot clear a task or plan blocker.

After the required tasks are accepted, apply the independent final-audit
decision explicitly:

```bash
agent-lifecycle workflow final-audit-outcome \
  --state work/run.state.json \
  --operation-id final-audit-outcome-1 \
  --expected-revision 12 \
  --source-revision <source-sha> \
  --final-audit final/final-audit.json \
  --verdict REWORK \
  --task-id WS-01 \
  --finding-id F-001 \
  --reason "address the independent finding"
```

`ACCEPTED` proceeds to the existing finalization gates. `REWORK` archives the
named accepted attempts and preserves their files, `CONTRACT_CHANGE` requires
a new frozen plan, and `BLOCKED` waits for the declared external action. None
of these transitions changes a frozen plan or raises a retry budget.

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

## Bug Forensics repair

For defects, regressions, flaky failures, incidents and security bugs, start
with task intake and let ALK add advisory-only Bug Forensics markers:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode plan \
  --file work/bugs/checkout-regression.md \
  --out work/bugs/checkout-start.json
```

The advisory does not activate the workflow gate. A reviewed frozen plan must
explicitly opt in before the gate can require reproduction, fingerprint,
hypothesis ledger, regression proof and fix-impact receipts.

See [Bug Forensics workflows](bug-forensics-workflows.md) for concrete defect
search, regression, flaky failure and security-bug examples.

## Coordinate cross-review

For higher-risk research, planning or audits, create reviewer assignments with
`review-mesh assign`, run the reviewers outside ALK, import their JSON output,
then synthesize and check quorum.

See [Review Mesh workflow scenarios](review-mesh-workflow.md) for concrete
Codex, Claude and OpenCode/GLM examples. GLM is only an example model behind
OpenCode; any configured model can be used by changing the host command.

## Safety rules

- Do not put secrets or private environment values in task files.
- Prefer relative repository paths in portable packets.
- Treat `review-mesh recommend` as advice until a frozen plan opts in.
- Plugin installation alone is not proof that the ALK lifecycle ran.
- Raw text, Markdown and imported plans never authorize implementation by
  themselves.

Use `agent-lifecycle start` for the common path. Advanced scripts may use the
atomic `adapter task start`, `adapter run` and `adapter session resume`
commands when they need direct control over one lifecycle primitive.
