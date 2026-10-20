---
name: agent-first-planning
description: Create or revise production-ready SDD plans for agent execution, including clarification, specification, freeze inputs, ownership, budgets, and evidence contracts.
---

# Agent first planning

## Contract

Prepare scope, SDD tier, specification when required, developer overview, exact ownership, acceptance, evidence and finite budgets. Planning is draft-only until independent audit-agent-plan returns READY_TO_FREEZE and a reviewed lock is created. Never implement during planning.

Read [the complete lifecycle contract](references/lifecycle-contract.md) before
acting in this stage. It preserves every original instruction; this entrypoint
is a routing summary, not a replacement contract. Follow its linked shared
contracts for the selected task.

Use plan verify as the read-only structural preflight; freeze-prepare only prepares a new candidate, never review or execution permission.

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
`docs/reference/safe-artifact-authoring.md`.

Full contract SHA256: `e8dc5e8e01c2db420f72da8fcc8fc0f5a9e5e1c1e65aadb3df049b8dfcf0735e`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.
