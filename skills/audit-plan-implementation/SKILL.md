---
name: audit-plan-implementation
description: Independently audit a task attempt or completed run against a frozen plan, checking ownership, evidence, acceptance, and final readiness.
---

# Audit plan implementation

## Inputs

Independently compare current source-bound task result and evidence with the frozen contract, ownership and every acceptance criterion. Preserve failures and missing evidence. Semantic review must precede the actual typed audit; no self-review or fabricated positive report.

Read [the complete lifecycle contract](references/lifecycle-contract.md) before
acting in this stage. It preserves every original instruction; this entrypoint
is a routing summary, not a replacement contract. Follow its linked shared
contracts for the selected task.

Read docs/guides/lifecycle-cookbook.md#audit-implementation-evidence. A typed audit validates bound artifacts, not an invented independent judgement. Final audit requires all required tasks accepted and actual native finalization.

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
`docs/reference/safe-artifact-authoring.md`.

Full contract SHA256: `6dc7f14c8888c89bd91e1eae00eabd6ddb728476b5784cf89cb56b482bd6d10f`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.


## Adapter lifecycle evidence

Check GUIDANCE_ONLY, OBSERVED and ENFORCED evidence against the qualified route;
NO_RECOMMENDATION is not enforced support. A claim in a prompt or skill does not
prove a host-owned pre-action boundary. Reject a stale receipt or mismatched
operation identity. Follow the complete reference for the existing typed gates.
