---
name: agent-first-planning
description: Create or revise production-ready SDD plans for agent execution, including clarification, specification, freeze inputs, ownership, budgets, and evidence contracts.
---

# Agent first planning

Use this skill when a request must become an agent-ready implementation plan
before work starts. The output is a frozen-ready package, not implementation.

## Contract

1. Clarify only questions that can change scope, architecture, safety,
   acceptance, external authority, or write ownership. Record safe assumptions
   for everything else.
2. Choose the SDD tier.
   - `S0`: one bounded mechanical change with one executable owner.
   - `S1`: one standard owner and no major architecture, security,
     performance, browser, data, or external-environment risk.
   - `S2`: multiple executable owners or meaningful architecture, security,
     performance, browser, data, release, migration, or external risk.
   Use the core `tier resolve` command when available, and never lower a tier
   without independent review.
3. For `S2`, write a product specification first and require independent
   specification review before plan freeze.
4. Produce a developer overview that explains the intent, user-visible result,
   architecture boundaries, risks, non-goals, and execution model.
5. Produce a plan manifest or equivalent machine-readable contract with:
   requirements, acceptance criteria, evidence ids, workstreams, dependency DAG,
   exact write ownership, read-only inputs, lead-owned integration seams,
   validation commands, budgets, context limits, and final audit gates.
6. Keep immutable planning authority separate from mutable run artifacts.
7. Route the candidate plan to `audit-agent-plan`. Revise until it is
   `READY_TO_FREEZE`, explicitly blocked, or the review budget is exhausted.

When the CLI is available, run the structural gate before independent review:

```bash
agent-lifecycle plan completeness-check --manifest <plan.manifest.json>
agent-lifecycle plan check --manifest <plan.manifest.json> --require-completeness
```

The goal is compact-but-complete authority for the selected tier, not long
prose. S0/S1 plans can stay short, but the fields required by their tier must
be present.

## Planning rules

- Do not implement code while planning.
- Do not assign shared integration to a worker by hiding it in another task.
- Do not depend on chat history as authority when a plan package exists.
- Do not claim production readiness without tests, evidence, rollback or
  release gates appropriate to the risk.
- Keep plans small enough for workers: active packet, exact files, acceptance
  criteria, and evidence routes only.
- For small-context hosts, require compact packet rendering with
  `small-context-profile.v1`; do not depend on full plan context.
- Do not use shortness as a reason to omit required tier structure. Missing
  evidence routes, write ownership, budgets, context limits, or final gates are
  blockers when the selected tier requires them.

## Output

Return these artifacts or their host-native equivalents:

- clarification log and assumptions;
- SDD product specification when required;
- developer overview;
- plan manifest;
- plan lock or freeze candidate identity;
- exact worker write-set manifest;
- validation and evidence plan;
- plan review request.

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
