---
name: audit-agent-plan
description: Independently audit SDD specifications and agent-ready plans before freeze, returning findings, readiness verdicts, and required refinements.
---

# Audit Agent Plan

Use this skill for independent review of a candidate specification or
agent-ready plan. The default action is audit only.

## Inputs

Read the developer overview first, then the specification, plan manifest,
write-set contract, worker DAG, acceptance checklist, evidence plan, budget
profile, and previous review if this is a revision.

## Review Matrix

Check every item for:

- traceability from requirement to acceptance criterion, workstream, evidence,
  and final audit gate;
- SDD tier correctness;
- missing clarification or unsafe assumption;
- architecture, security, performance, data, browser, release, or external
  environment risks;
- exact ownership and forbidden writes;
- dependency DAG correctness and parallel safety;
- validation commands that are executable, scoped, bounded, and sufficient;
- context and token budget fit for small and large context hosts;
- deterministic SDD tier resolution evidence or a justified higher-tier
  override;
- plan/freeze/run artifact separation;
- adapter neutrality and absence of project-specific assumptions unless the
  target project explicitly owns them.

## Verdicts

- `READY_TO_FREEZE`: no open Medium or High finding; freeze inputs are complete.
- `CHANGES_REQUIRED`: the plan can be corrected within the current intent.
- `BLOCKED`: external authority or missing product decision prevents a safe
  plan.
- `REOPEN_REQUIRED`: a frozen plan needs contract, ownership, or intent changes.

## Rules

- Findings first; do not hide blockers in prose.
- Do not rewrite the plan during independent review unless explicitly asked.
- Do not approve a plan that lacks a developer overview, write ownership,
  evidence gates, or final audit route.
- Do not accept self-review as independent review.
- Do not downgrade required runtime, security, or performance evidence to
  synthetic-only checks unless the plan explicitly narrows the claim.

## Output

Return:

- findings ordered by severity;
- coverage matrix;
- missing or excessive scope;
- validation of budgets and context fit;
- freeze verdict;
- exact edits required before the next review.
