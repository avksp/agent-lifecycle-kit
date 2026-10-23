---
name: audit-agent-plan
description: Independently audit SDD specifications and agent-ready plans before freeze, returning findings, readiness verdicts, and required refinements.
---

# Audit agent plan

Use this skill for independent review of a candidate specification or
agent-ready plan. The default action is audit only.

## Inputs

Read the developer overview first, then the specification, plan manifest,
write-set contract, worker DAG, acceptance checklist, evidence plan, budget
profile, and previous review if this is a revision.

## Review matrix

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
- optional Review Mesh scope: any blocking multi-review requirement must be
  off by default, provider-neutral, token/resource capped, phase-scoped, and
  backed by assignment/result/synthesis/quorum evidence routes.

When available, run `agent-lifecycle plan completeness-check --manifest
<plan.manifest.json>` and treat `agent-plan-completeness-validation.v1` blockers
as deterministic pre-audit findings. For freeze gates that opt in to structural
enforcement, also check `agent-lifecycle plan check --require-completeness`.
For Markdown-only plan packages or plan folders, use the cookbook path in
`docs/guides/lifecycle-cookbook.md` and `docs/guides/code-review-workflows.md`
to keep the review draft-only until a real ALK plan is frozen.

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
- Do not ask for longer prose when the defect is missing structure. Require the
  smallest tier-appropriate field or receipt route that closes the blocker.
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

## Bounded capability feasibility before freeze

For a new route, portability claim or changed supported scenario, bind the claim
to 1–3 actual entrypoints, the lower capability/authority boundary, one existing
negative case and exact write owners before freeze. Distinguish refactoring
existing behavior from adding a capability. UNIT_ONLY or mock evidence cannot
establish an end-to-end route. If the existing boundary refuses the claimed
scenario, obtain the user's scope decision before freeze: narrow the claim or
include the required lower-layer changes and owners. If 1–3 entrypoints are
insufficient, scope a bounded feasibility probe before freeze; do not repeat a
whole audit. Record this in the existing specification/evidence plan and review;
no extra audit stage, manifest schema or mandatory receipt framework is added.
Structural plan verify/ownership/traceability checks do not prove semantic reachability.

Example: Release 2.24 WS-03 keeps `resolve_declared_ledger_context`'s
`declared-ledger-route-unsupported` refusal and the existing
`test_unsupported_package_and_rebound_opening_refuse` negative case. Its typed
usage-interface fixture is UNIT_ONLY. Isolating legacy paths is a refactor;
a generic financial ledger or a newly qualified host route would be a separate
capability requiring lower-layer ownership and end-to-end evidence.

The independent plan reviewer verifies this bounded mapping within the existing
plan review and blocks an unsupported positive claim before READY_TO_FREEZE.
