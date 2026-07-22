---
name: agent-first-planning
description: Create or revise production-ready SDD plans for agent execution, including clarification, specification, freeze inputs, ownership, budgets, and evidence contracts.
---

# Agent First Planning

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

## Planning Rules

- Do not implement code while planning.
- Do not assign shared integration to a worker by hiding it in another task.
- Do not depend on chat history as authority when a plan package exists.
- Do not claim production readiness without tests, evidence, rollback or
  release gates appropriate to the risk.
- Keep plans small enough for workers: active packet, exact files, acceptance
  criteria, and evidence routes only.
- For small-context hosts, require compact packet rendering with
  `small-context-profile.v1`; do not depend on full plan context.

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
