# Review Mesh workflow cookbook

This guide shows how to use Review Mesh without turning ALK into a model
broker. ALK prepares assignments, imports reviewer output, synthesizes findings
and checks quorum. The operator or host wrappers still run the reviewers.

Use this guide when a task needs stronger planning or audit confidence:

- research before implementation;
- architecture or risk analysis;
- plan review by more than one adapter;
- implementation audit by several reviewers;
- high-risk bug, security or release work.

For ordinary low-risk edits, keep the default lifecycle and skip Review Mesh.
For a shorter scenario map, start with [Lifecycle cookbook](lifecycle-cookbook.md).

## Choose the right path

| User level | Use | Commands |
| --- | --- | --- |
| Beginner | Decide whether extra review is useful | `adapter task start`, `review-mesh recommend` |
| Intermediate | Prepare a small review panel | `recommend`, `prepare`, `import-result`, `synthesize`, `quorum` |
| Advanced | Wire Review Mesh into frozen gates | atomic `review-mesh` commands plus `--review-mesh-quorum` |

## Common task recipes

### Research or planning only

Use this when the desired output is an analysis, architecture note or plan, not
code. Put the task in Markdown, run `adapter task start --file`, then run
`review-mesh recommend`. If the advisor recommends
`parallel-research-synthesis`, generate assignments with
`--mode parallel-research-synthesis --phase plan-review`.

Stop after `review-mesh synthesize` or `review-mesh quorum`. The synthesis is
the deliverable; no implementation task is authorized unless a reviewed plan is
created and frozen later.

### One lead draft with independent reviewers

Use `leader-draft-multi-review` when one adapter or operator has already
prepared a plan and you want two or more reviewers to check scope, missing
evidence, write ownership, rollback steps and release risk. Review Mesh stores
the review packets and result receipts, while the plan owner still decides which
findings are accepted.

### Bug or regression investigation

Start with `adapter task start --file bug.md` and let intake mark defect-shaped
signals. Bug Forensics may be recommended for reproduction, failure
fingerprints and regression proof. Review Mesh is useful around that profile:
use `leader-draft-multi-review` for root-cause and fix-plan review, then use
`implementation-audit-panel` after the patch to review the evidence.

Raw bug text still does not authorize implementation. It becomes executable only
through the normal reviewed plan or frozen run-request path.

### Implementation audit panel

Use `implementation-audit-panel` after a worker has produced a task result and
evidence. Each reviewer receives an assignment focused on acceptance criteria,
changed files, evidence freshness and collateral-damage risk. When the plan
requires Review Mesh for this phase, pass the quorum receipt to:

```bash
agent-lifecycle audit implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --review-mesh-quorum work/review-mesh/implementation-quorum.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

### Security or release final check

Use Review Mesh as a final high-risk check only when the frozen plan asks for
it. Reviewers should focus on release claims, secret redaction, local-path
leaks, unsupported adapter claims, rollback instructions and evidence gaps. The
final quorum receipt can be passed to `workflow finalize`.

### Small or local model support

Review Mesh can improve quality without forcing a single large model. Keep
assignments compact, use neutral reviewer ids and model classes, and split the
task by phase. Small reviewers can check narrow packets, while the synthesis
step records the combined findings and unresolved gaps.

## Beginner path: get advice only

Create a task file:

```markdown
# Task

Research the current adapter session flow and write a plan for improving
resume behavior. Do not implement yet.
```

Start adapter-specific intake. This does not start implementation:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file task.md \
  --out intake.json
```

Ask whether Review Mesh is worth using:

```bash
agent-lifecycle review-mesh recommend \
  --intake intake.json \
  --out review-mesh-recommendation.json
```

If the recommendation is `off`, keep the normal ALK workflow. If it recommends
`leader-draft-multi-review`, `parallel-research-synthesis` or
`implementation-audit-panel`, treat that as advice. It becomes mandatory only
after a reviewed frozen plan opts in.

## Quick prepare path: one command for packets

Use `prepare` when the recommendation says that several reviewers are useful
and you want ALK to create the local profile and assignment packets:

```bash
agent-lifecycle review-mesh prepare \
  --intake intake.json \
  --template parallel-research-synthesis \
  --reviewer codex-example:architecture-reviewer:strong-reasoning \
  --reviewer claude-example:risk-reviewer:strong-reasoning \
  --reviewer opencode-glm-example:local-reviewer:local-strong-review \
  --evidence-id EV-PLAN \
  --out-dir work/review-mesh/plan-review \
  --out work/review-mesh/prepare-receipt.json
```

This writes:

- `work/review-mesh/plan-review/profile.json`;
- one assignment packet per reviewer under
  `work/review-mesh/plan-review/assignments/`;
- `work/review-mesh/prepare-receipt.json`.

The reviewer ids above are examples. Codex, Claude Code and OpenCode/GLM are
replaceable host choices. The exact model is selected in the host CLI or its
local config; ALK stores only provider-neutral model classes such as
`strong-reasoning` and `local-strong-review`.

Give each assignment packet to the selected CLI. For OpenCode/GLM, GLM-5.2 is
only an example:

```bash
opencode models <provider>
opencode run --model <provider>/<model-id> --format json \
  --file work/review-mesh/plan-review/assignments/parallel-research-synthesis-3.json \
  "Review the assignment and return only reviewer-output.v1 JSON" \
  > reviewer-glm-output.json
```

### Review one Markdown task file

When the task already lives in Markdown, pass that file as the single intake
source. For example, `tasks/review/adapter-sessions.md` can contain the research
request, the no-implementation boundary and the expected output:

```markdown
# Task

Review the current managed adapter session flow and write an improvement plan.
Do not implement yet.

Check:
- lifecycle completeness;
- safe resume behavior;
- whether the plan avoids creating a second agent runtime.
```

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file tasks/review/adapter-sessions.md \
  --out intake.json

agent-lifecycle review-mesh recommend \
  --intake intake.json \
  --out review-recommendation.json
```

### Review a directory of Markdown files

`--file` accepts one prepared input file. If a plan is split across several
`.md` files, use one of two safe patterns.

When reviewers work in the same repository, create a task that points at the
directory:

```bash
cat > task.md <<'EOF'
# Task

Review the Markdown plan package in `tasks/release-1-40/`.
Read every `.md` file in that directory.

Focus on:
- requirements and acceptance criteria;
- evidence and validation commands;
- file ownership;
- security and release risks.

Do not implement. Return only findings and a final recommendation.
EOF

agent-lifecycle adapter task start --adapter codex --file task.md --out intake.json
agent-lifecycle review-mesh recommend --intake intake.json --out review-recommendation.json
```

When the review packet must be portable and should not depend on repository
access, combine the Markdown files into one deterministic input file with shell
commands:

```bash
mkdir -p work/group-review
{
  printf '# Task\n\n'
  printf 'Review the combined Markdown plan package. Do not implement.\n\n'
  find tasks/release-1-40 -maxdepth 1 -name '*.md' -print | sort | while IFS= read -r file; do
    printf '\n\n---\n\n## %s\n\n' "$file"
    cat "$file"
  done
} > work/group-review/plan-review-input.md

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/group-review/plan-review-input.md \
  --out intake.json

agent-lifecycle review-mesh recommend \
  --intake intake.json \
  --out review-recommendation.json
```

## Manual path: run a small review panel

Create a profile once for the review. The profile stores token/resource caps
and neutral independence rules:

```bash
agent-lifecycle review-mesh profile \
  --profile-id rm-plan-review \
  --default-mode leader-draft-multi-review \
  --reviewer-model-class strong-reasoning \
  --reviewer-model-class local-strong-review \
  --max-invocations 3 \
  --max-input-tokens 12000 \
  --max-output-tokens 3000 \
  --max-wall-seconds 900 \
  --out rm-profile.json
```

Create one assignment per reviewer. The reviewer ids below are examples; they
are not provider or model names:

```bash
agent-lifecycle review-mesh assign \
  --intake intake.json \
  --profile rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-PLAN-A \
  --reviewer-id reviewer-a \
  --reviewer-role plan-reviewer \
  --reviewer-model-class strong-reasoning \
  --out rm-assignment-a.json

agent-lifecycle review-mesh assign \
  --intake intake.json \
  --profile rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-PLAN-B \
  --reviewer-id reviewer-b \
  --reviewer-role plan-reviewer \
  --reviewer-model-class local-strong-review \
  --out rm-assignment-b.json
```

### Concrete host examples

The adapter decides the concrete model in host-local configuration or explicit
host CLI flags. ALK records provider-neutral model classes and optional identity
hashes, not raw provider/model names.

Use explicit host flags when you want the selected model to be clear:

```bash
codex exec --model <codex-model-id> \
  "Review rm-assignment-a.json and return only reviewer-output.v1 JSON" \
  > reviewer-a-output.json

claude --model <claude-model-alias> --print --output-format json \
  "Review rm-assignment-b.json and return only reviewer-output.v1 JSON" \
  > reviewer-b-output.json

opencode models <provider>
opencode run --model <provider>/<model-id> --format json \
  --file rm-assignment-glm.json \
  "Review the assignment and return only reviewer-output.v1 JSON" \
  > reviewer-glm-output.json
```

For OpenCode, first confirm the model appears in `opencode models <provider>`,
then pass the same `<provider>/<model-id>` to `opencode run --model`. GLM-5.2 is
only an example: if it is configured in your OpenCode setup, the model may look
like `<provider>/glm-5.2`; otherwise replace it with any other configured model.

If a frozen plan requires independence evidence, pass neutral hashes into the
assignment. Keep the raw model name in host-local notes, not in the portable
plan:

```bash
MODEL_ID='<provider>/glm-5.2'
MODEL_HASH=$(printf '%s' "opencode:${MODEL_ID}" | shasum -a 256 | cut -d ' ' -f 1)

agent-lifecycle review-mesh assign \
  --intake intake.json \
  --profile rm-profile.json \
  --mode parallel-research-synthesis \
  --phase plan-review \
  --assignment-id RM-GLM \
  --reviewer-id opencode-glm-reviewer \
  --reviewer-role plan-reviewer \
  --reviewer-model-class strong-reasoning \
  --reviewer-model-identity-hash "$MODEL_HASH" \
  --out rm-assignment-glm.json
```

`MODEL_ID='<provider>/glm-5.2'` is a GLM example. Replace it with a Codex,
Claude, Qwen, local or other model id supported by the selected CLI.

Give each assignment packet to the chosen host adapter or operator. ALK does
not launch those reviewers. Each reviewer should return a small JSON object
with findings and token/resource usage:

```json
{
  "schemaVersion": "reviewer-output.v1",
  "status": "FAIL",
  "budgetUsage": {
    "invocations": 1,
    "inputTokens": 12000,
    "outputTokens": 1800,
    "wallSeconds": 420
  },
  "findings": [
    {
      "id": "PLAN-1",
      "severity": "MEDIUM",
      "status": "open",
      "message": "The plan needs an explicit rollback step for failed resume."
    }
  ]
}
```

Import each reviewer output:

```bash
agent-lifecycle review-mesh import-result \
  --profile rm-profile.json \
  --assignment rm-assignment-a.json \
  --reviewer-output reviewer-a-output.json \
  --out rm-result-a.json

agent-lifecycle review-mesh import-result \
  --profile rm-profile.json \
  --assignment rm-assignment-b.json \
  --reviewer-output reviewer-b-output.json \
  --out rm-result-b.json
```

Import redacts secret-like markers and rejects local absolute paths unless the
plan explicitly allows local evidence references.

Synthesize findings:

```bash
agent-lifecycle review-mesh synthesize \
  --profile rm-profile.json \
  --result rm-result-a.json \
  --result rm-result-b.json \
  --out rm-synthesis.json
```

If the lead has resolved findings, record that explicitly:

```bash
agent-lifecycle review-mesh synthesize \
  --profile rm-profile.json \
  --result rm-result-a.json \
  --result rm-result-b.json \
  --accepted-finding-id PLAN-1 \
  --out rm-synthesis.json
```

Build the quorum receipt:

```bash
agent-lifecycle review-mesh quorum \
  --profile rm-profile.json \
  --synthesis rm-synthesis.json \
  --min-reviewers 2 \
  --required-role plan-reviewer \
  --reviewer-role plan-reviewer \
  --reviewer-role plan-reviewer \
  --out rm-quorum.json
```

The quorum receipt is evidence. It does not replace plan review, implementation
audit or final proof.

## Advanced path: require quorum in a frozen plan

Review Mesh blocks only when the frozen plan explicitly opts in. A plan-level
configuration can require quorum for selected phases:

```json
{
  "reviewMesh": {
    "required": true,
    "phases": ["freeze", "implementation-audit", "final-audit"],
    "profileDigest": "<profileDigest from rm-profile.json>",
    "quorumReceiptPath": "work/review-mesh/freeze-quorum.json"
  }
}
```

Use `quorumReceiptPath` for freeze-time adoption checks. For implementation
audit and final audit, pass the phase-specific quorum receipt explicitly:

```bash
agent-lifecycle audit implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --review-mesh-quorum work/review-mesh/implementation-quorum.json \
  --out work/WS-01/attempt-1/implementation-audit.json

agent-lifecycle workflow finalize \
  --state run.state.json \
  --operation-id finalize-op \
  --expected-revision 12 \
  --source-revision "$(git rev-parse HEAD)" \
  --final-audit final/final-audit.json \
  --review-mesh-quorum work/review-mesh/final-quorum.json \
  --proof final/final-proof.json \
  --reason "complete"
```

## Safety rules

- Review Mesh is off by default.
- Recommendations are advisory until a reviewed frozen plan opts in.
- ALK does not call provider APIs or launch reviewer CLIs.
- Portable contracts use neutral reviewer ids and model classes, not concrete
  provider or model names.
- Budgets are tokens, invocation counts and wall-clock resources.
- Imported reviewer output should not contain raw secrets or private local
  paths.

## Practical checklist

1. Start with `adapter task start --file task.md`.
2. Run `review-mesh recommend`.
3. If extra review is useful, create `rm-profile.json`.
4. Generate one assignment per reviewer.
5. Run reviewers outside ALK.
6. Import reviewer outputs.
7. Synthesize findings.
8. Build quorum.
9. Attach quorum only to phases that the frozen plan requires.
