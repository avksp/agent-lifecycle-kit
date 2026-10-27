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

Read the [common route](../../docs/guides/lifecycle-cookbook.md#canonical-execution-route),
[recipe table](../../docs/guides/lifecycle-cookbook.md#choose-a-recipe) and
[safety rules](../../docs/guides/lifecycle-cookbook.md#safety-rules). Read
[the implementation audit recipe](../../docs/guides/lifecycle-cookbook.md#audit-implementation-evidence) and its required links.
A typed audit validates bound artifacts, not an invented independent judgement.
Final audit requires all required tasks accepted and actual native finalization.

For new capability claims, apply the bounded pre-freeze feasibility mapping in
the linked contract: actual entrypoints, lower authority, negative case and owners.

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
[safe artifact authoring](../../docs/reference/safe-artifact-authoring.md).

Full contract SHA256: `de42b0282e75ce75bff1dd37f4c1e91a8f2ad354750db8596d116986018af526`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.


## Adapter lifecycle evidence

Check GUIDANCE_ONLY, OBSERVED and ENFORCED evidence against the qualified route;
NO_RECOMMENDATION is not enforced support. A claim in a prompt or skill does not
prove a host-owned pre-action boundary. Reject a stale receipt or mismatched
operation identity. Follow the complete reference for the existing typed gates.

Resource paths are relative to this installed skill root. The package supplies
its required documents; a consumer project is not their fallback source.
