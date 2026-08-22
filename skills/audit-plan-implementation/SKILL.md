---
name: audit-plan-implementation
description: Independently audit a task attempt or completed run against a frozen plan, checking ownership, evidence, acceptance, and final readiness.
---

# Audit plan implementation

Use this skill for findings-first verification after implementation work. The
default action is audit only; fixes require an explicit remediation request or
a controller policy that allows bounded in-scope remediation.

## Inputs

Read the frozen developer overview, plan manifest, lock, task packet, write-set
contract, acceptance criteria, evidence rules, task result, implementation
diff, and previous reviews. In final mode, read all accepted task results,
reviews, evidence receipts, and the workflow state.

When the installed CLI exposes the implementation audit facade, use it as the
typed evidence producer:

```bash
agent-lifecycle audit implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --review-mesh-quorum work/review-mesh/implementation-quorum.json \
  --out work/WS-01/attempt-1/implementation-audit.json

agent-lifecycle audit final-implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --report work/WS-01/attempt-1/implementation-audit.json \
  --out final/final-implementation-audit.json
```

The command output is the machine-readable source for acceptance gates. The
skill still supplies semantic review guidance when a human or host reviewer must
interpret findings.

Use `--review-mesh-quorum` only when the frozen plan requires Review Mesh for
the audited phase. Missing or failed quorum evidence is a blocking audit
finding; optional Review Mesh output remains advisory.
For operator-facing audit setup, point beginners to
`docs/guides/lifecycle-cookbook.md#audit-implementation-evidence` and keep this
skill focused on findings-first semantic verification plus typed audit
receipts.

## Task audit

For each planned item, verify:

- expected behavior and acceptance criteria;
- actual changed files and their owner;
- forbidden-write and read-only-path compliance;
- tests, command receipts, artifact ids, hashes, and freshness;
- evidence limits and budget use;
- architecture, security, performance, release, and adapter constraints;
- task result identity bound to run, task, attempt, packet, plan, source, and
  reviewer.

For adapter lifecycle control, also verify the operation-specific declared,
supported and qualified levels in the descriptor and capability manifest.
Treat `GUIDANCE_ONLY` as instructions only, require exact-host live evidence
for `ENFORCED`, and treat `OBSERVED` as recorded outcome evidence rather than
pre-action prevention. Treat `NO_RECOMMENDATION` or a stale receipt as a
finding when the frozen plan selects a stronger level. Check the host-owned
pre-action decision, post-action binding and stop evidence; a prompt or skill
alone is not enforcement.

## Verdicts

- `ACCEPTED`: task scope, ownership, evidence, and review pass with no open
  Medium or High finding.
- `REWORK`: implementation, test, or evidence defects remain inside the frozen
  scope.
- `CONTRACT_CHANGE`: intent, architecture, ownership, write set, acceptance, or
  proof rules must be reopened and refrozen.
- `BLOCKED`: external state prevents a safe verdict.

## Final audit

Before completion, verify that every required task is accepted, every required
requirement and acceptance criterion is covered exactly, external writers are
quiescent, final validation passes, and the final proof binds plan, packets,
state, results, reviews, evidence, source, and release inventory.

## Rules

- Findings first, ordered by severity.
- Do not accept prose-only proof.
- Do not accept worker self-certification without independent review.
- Do not silently fix architecture, ownership, or contract violations.
- Do not broaden scope to unrelated changes unless they block the plan.

## Output

Return findings, coverage matrix, validation commands and outcomes, verdict,
dependency unlock status, required remediation, and whether refreeze is needed.
For CLI-backed runs, emit or reference `agent-implementation-audit-report.v1`
for each accepted task and `agent-final-implementation-audit.v1` before final
workflow proof.
