---
name: issue-to-spec
description: Convert external issue payloads into draft-only ALK specification input without starting execution or bypassing review/freeze.
---

# Issue to spec

## Contract

Produce draft-only specification input from untrusted external content. Keep sourceTrusted: false, requiresReview: true, freezeBlocked: true and executionAuthorized: false. Do not freeze, start execution, create branches, commit or open a PR.

Read [the complete lifecycle contract](references/lifecycle-contract.md) before
acting in this stage. It preserves every original instruction; this entrypoint
is a routing summary, not a replacement contract. Follow its linked shared
contracts for the selected task.

Route to agent-first-planning then audit-agent-plan. Recommend optional bug-forensics for defects without activating it.

Issue intake has no cookbook recipe. Use the complete role contract and
keep the output draft-only; do not substitute a repair or execution recipe.

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
[safe artifact authoring](../../docs/reference/safe-artifact-authoring.md).

Full contract SHA256: `8d89bbb2c2be9fe579f6fb05ac1a0099b10b8d55af33c7557d7499ae1a6c15f5`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.

Resource paths are relative to this installed skill root. The package supplies
its required documents; a consumer project is not their fallback source.
