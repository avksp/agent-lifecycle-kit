# Code review workflows

Use ALK for code review when the important question is not only "does the diff
look good?", but whether the change fits the task, architecture, evidence and
release boundary. ALK can review a local diff, a GitHub pull request, a GitLab
merge request, a Markdown plan package, or a completed implementation attempt.

ALK does not need to own GitHub or GitLab access. Prepare the diff and task
context with normal Git or host CLI commands, then pass one Markdown task file
to `adapter task start`. Raw text and Markdown stay review-gated: they do not
authorize implementation.

## Choose the review path

| Case | Use this path | Main commands |
| --- | --- | --- |
| Architecture is documented | Review the diff against known architecture and contracts. | `adapter task start`, optional `review-mesh recommend` |
| Architecture is not documented | First recover architecture boundaries, then review the diff. | `adapter task start`, `review-mesh recommend` |
| GitHub pull request | Check out or fetch the PR, save a diff, review that packet. | `gh pr checkout` or `git fetch`, then `adapter task start` |
| GitLab merge request | Fetch the MR branch, save a diff, review that packet. | `git fetch`, then `adapter task start` |
| Plan package only | Review Markdown plan files without implementation. | `adapter task start`, `review-mesh recommend` |
| Completed ALK task | Audit the result against the frozen plan and evidence. | `audit implementation` |
| High-risk review | Coordinate more than one reviewer and require quorum only if the frozen plan opts in. | `review-mesh assign/import-result/synthesize/quorum` |

## Prepare a review packet

Keep the review packet explicit. Put the task, diff path, architecture links,
risk focus and output format in one Markdown file.

```bash
mkdir -p work/code-review/pr-123
```

Example task file:

```markdown
# Task

Review the change in `work/code-review/pr-123/diff.patch`.
Do not implement.

Architecture and contracts:
- docs/architecture.md
- docs/reference/public-contracts.md

Check:
- architecture fit and module boundaries;
- logic errors and edge cases;
- security and data handling;
- SOLID, DRY and KISS;
- test coverage and missing evidence;
- migration, compatibility and release risk.

Return:
- findings ordered by severity;
- merge blockers;
- optional follow-up items;
- required validation commands.
```

Start the ALK intake:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/pr-123/review-task.md \
  --out work/code-review/pr-123/intake.json
```

Ask whether several reviewers are useful:

```bash
agent-lifecycle review-mesh recommend \
  --intake work/code-review/pr-123/intake.json \
  --out work/code-review/pr-123/recommendation.json
```

The recommendation is advisory until a reviewed frozen plan explicitly requires
it.

## Review a GitHub pull request

If GitHub CLI is available:

```bash
gh pr checkout 123
mkdir -p work/code-review/pr-123
git diff origin/main...HEAD > work/code-review/pr-123/diff.patch
```

Without GitHub CLI:

```bash
git fetch origin pull/123/head:review/pr-123
mkdir -p work/code-review/pr-123
git diff origin/main...review/pr-123 > work/code-review/pr-123/diff.patch
```

Then create `work/code-review/pr-123/review-task.md` and run:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/pr-123/review-task.md \
  --out work/code-review/pr-123/intake.json
```

Use this for normal PR review, architecture review, security review, or
pre-merge risk review. Do not include secrets or private environment values in
the task file.

## Review a GitLab merge request

Fetch the merge request branch and build the same kind of packet:

```bash
git fetch origin merge-requests/45/head:review/mr-45
mkdir -p work/code-review/mr-45
git diff origin/main...review/mr-45 > work/code-review/mr-45/diff.patch
```

Create `work/code-review/mr-45/review-task.md`:

```markdown
# Task

Review GitLab merge request 45 using `work/code-review/mr-45/diff.patch`.
Do not implement.

Check architecture fit, defects, security, tests, ownership and release risk.
Return findings first, then a merge verdict.
```

Run intake and recommendation:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/mr-45/review-task.md \
  --out work/code-review/mr-45/intake.json

agent-lifecycle review-mesh recommend \
  --intake work/code-review/mr-45/intake.json \
  --out work/code-review/mr-45/recommendation.json
```

Some GitLab installations use different protected branch names or refspecs.
That is outside ALK; the review packet only needs a stable diff and clear task
context.

## Review when architecture is documented

When architecture exists, make it the source of truth for the review:

```markdown
# Task

Review `work/code-review/pr-123/diff.patch` against the documented architecture.
Do not implement.

Architecture:
- docs/architecture/modular-controller.md
- docs/reference/source-of-truth.md
- docs/reference/public-contracts.md

Focus:
- whether the changed files belong to the right layer;
- whether new abstractions are justified;
- whether contracts remain additive;
- whether tests prove the intended behavior;
- whether release or adapter claims were broadened.
```

This path is best for architecture-sensitive code, public contracts, adapters,
security boundaries, migration code and release work.

## Review when architecture is missing

If architecture is not documented, do not pretend the reviewer already knows
the boundaries. Ask for architecture discovery first:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --text "Analyze the repository and the diff in work/code-review/pr-123/diff.patch. First recover the module responsibilities and architecture boundaries, then review the diff against that recovered map. Do not implement." \
  --out work/code-review/pr-123/intake.json
```

Expected output:

- a compact architecture map;
- uncertain assumptions;
- review findings;
- missing tests or evidence;
- whether a formal plan should be created before implementation.

For larger or risky changes, use `parallel-research-synthesis` so reviewers can
independently recover architecture and then compare conclusions.

## Review a Markdown plan package

For a plan split across several Markdown files, either point reviewers at the
directory or combine files into one packet.

Repository-local review:

```bash
cat > work/code-review/plan-review-task.md <<'EOF'
# Task

Review the Markdown plan package in `tasks/release-1-40/`.
Read every `.md` file in that directory.
Do not implement.

Check requirements, acceptance criteria, evidence routes, write ownership,
security gates and release claims.
EOF

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/plan-review-task.md \
  --out work/code-review/plan-intake.json
```

Portable packet:

```bash
mkdir -p work/code-review
{
  printf '# Task\n\n'
  printf 'Review the combined Markdown plan package. Do not implement.\n\n'
  find tasks/release-1-40 -maxdepth 1 -name '*.md' -print | sort | while IFS= read -r file; do
    printf '\n\n---\n\n## %s\n\n' "$file"
    cat "$file"
  done
} > work/code-review/plan-review-input.md

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/plan-review-input.md \
  --out work/code-review/plan-intake.json
```

## Coordinate several reviewers

Create a profile:

```bash
agent-lifecycle review-mesh profile \
  --profile-id rm-code-review \
  --default-mode leader-draft-multi-review \
  --reviewer-model-class strong-reasoning \
  --reviewer-model-class local-strong-review \
  --max-invocations 3 \
  --max-input-tokens 12000 \
  --max-output-tokens 3000 \
  --max-wall-seconds 900 \
  --out work/code-review/rm-profile.json
```

Create assignments:

```bash
agent-lifecycle review-mesh assign \
  --intake work/code-review/pr-123/intake.json \
  --profile work/code-review/rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-CODEX \
  --reviewer-id codex-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-model-class strong-reasoning \
  --out work/code-review/rm-codex.json

agent-lifecycle review-mesh assign \
  --intake work/code-review/pr-123/intake.json \
  --profile work/code-review/rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-CLAUDE \
  --reviewer-id claude-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-model-class strong-reasoning \
  --out work/code-review/rm-claude.json

agent-lifecycle review-mesh assign \
  --intake work/code-review/pr-123/intake.json \
  --profile work/code-review/rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-OPENCODE \
  --reviewer-id opencode-glm-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-model-class strong-reasoning \
  --out work/code-review/rm-opencode.json
```

Run reviewers outside ALK. These commands are examples; replace the model ids
with the models configured for your host:

```bash
codex exec --model <codex-model-id> \
  "Review work/code-review/rm-codex.json and return only reviewer-output.v1 JSON" \
  > work/code-review/codex-output.json

claude --model <claude-model-alias> --print --output-format json \
  "Review work/code-review/rm-claude.json and return only reviewer-output.v1 JSON" \
  > work/code-review/claude-output.json

opencode run --model <provider>/<model-id> --format json \
  --file work/code-review/rm-opencode.json \
  "Review the assignment and return only reviewer-output.v1 JSON" \
  > work/code-review/opencode-output.json
```

For OpenCode, `<provider>/<model-id>` can point to GLM or any other configured
model. ALK keeps the portable contract provider-neutral; concrete model choice
stays in the host command or host-local configuration.

Each reviewer returns a small JSON object:

```json
{
  "schemaVersion": "reviewer-output.v1",
  "status": "FAIL",
  "budgetUsage": {
    "invocations": 1,
    "inputTokens": 9000,
    "outputTokens": 1400,
    "wallSeconds": 360
  },
  "findings": [
    {
      "id": "CR-1",
      "severity": "MEDIUM",
      "status": "open",
      "message": "The diff changes the session boundary without a regression test."
    }
  ]
}
```

Import and combine reviewer output:

```bash
agent-lifecycle review-mesh import-result \
  --profile work/code-review/rm-profile.json \
  --assignment work/code-review/rm-codex.json \
  --reviewer-output work/code-review/codex-output.json \
  --out work/code-review/rm-result-codex.json

agent-lifecycle review-mesh import-result \
  --profile work/code-review/rm-profile.json \
  --assignment work/code-review/rm-claude.json \
  --reviewer-output work/code-review/claude-output.json \
  --out work/code-review/rm-result-claude.json

agent-lifecycle review-mesh import-result \
  --profile work/code-review/rm-profile.json \
  --assignment work/code-review/rm-opencode.json \
  --reviewer-output work/code-review/opencode-output.json \
  --out work/code-review/rm-result-opencode.json

agent-lifecycle review-mesh synthesize \
  --profile work/code-review/rm-profile.json \
  --result work/code-review/rm-result-codex.json \
  --result work/code-review/rm-result-claude.json \
  --result work/code-review/rm-result-opencode.json \
  --out work/code-review/rm-synthesis.json

agent-lifecycle review-mesh quorum \
  --profile work/code-review/rm-profile.json \
  --synthesis work/code-review/rm-synthesis.json \
  --min-reviewers 2 \
  --required-role code-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-role code-reviewer \
  --out work/code-review/rm-quorum.json
```

## Audit an ALK implementation

When the reviewed change was produced by a frozen ALK plan, use the
implementation audit command instead of a plain diff review:

```bash
agent-lifecycle audit implementation \
  --manifest tasks/release-x/plan.manifest.json \
  --state work/run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --review-mesh-quorum work/code-review/rm-quorum.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

Use `--review-mesh-quorum` only when the frozen plan requires several reviewers
for that phase. Otherwise a normal independent task review is enough.

## Safety checklist

- Keep raw tokens, API keys and private environment files out of task files and
  reviewer output.
- Prefer relative repository paths in portable review packets.
- Use `--allow-local-evidence-ref` only when the frozen plan explicitly allows
  local evidence references.
- Treat `review-mesh recommend` as advice until a frozen plan opts in.
- Do not merge on a self-review. High-risk changes need independent review or
  a recorded quorum receipt.
