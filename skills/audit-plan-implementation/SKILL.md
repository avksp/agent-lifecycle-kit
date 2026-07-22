---
name: audit-plan-implementation
description: Independently audit a task attempt or completed run against a frozen plan, checking ownership, evidence, acceptance, and final readiness.
---

# Audit Plan Implementation

Use this skill for findings-first verification after implementation work. The
default action is audit only; fixes require an explicit remediation request or
a controller policy that allows bounded in-scope remediation.

## Inputs

Read the frozen developer overview, plan manifest, lock, task packet, write-set
contract, acceptance criteria, evidence rules, task result, implementation
diff, and previous reviews. In final mode, read all accepted task results,
reviews, evidence receipts, and the workflow state.

## Task Audit

For each planned item, verify:

- expected behavior and acceptance criteria;
- actual changed files and their owner;
- forbidden-write and read-only-path compliance;
- tests, command receipts, artifact ids, hashes, and freshness;
- evidence limits and budget use;
- architecture, security, performance, release, and adapter constraints;
- task result identity bound to run, task, attempt, packet, plan, source, and
  reviewer.

## Verdicts

- `ACCEPTED`: task scope, ownership, evidence, and review pass with no open
  Medium or High finding.
- `REWORK`: implementation, test, or evidence defects remain inside the frozen
  scope.
- `CONTRACT_CHANGE`: intent, architecture, ownership, write set, acceptance, or
  proof rules must be reopened and refrozen.
- `BLOCKED`: external state prevents a safe verdict.

## Final Audit

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
