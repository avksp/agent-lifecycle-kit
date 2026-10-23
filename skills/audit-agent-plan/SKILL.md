---
name: audit-agent-plan
description: Independently audit SDD specifications and agent-ready plans before freeze, returning findings, readiness verdicts, and required refinements.
---

# Audit agent plan

## Inputs

Independently review specification, developer overview, requirements, ownership, DAG, evidence, budgets and final gates. Findings first; no self-review. READY_TO_FREEZE means complete reviewed planning inputs, not runtime or release proof.

Read [the complete lifecycle contract](references/lifecycle-contract.md) before
acting in this stage. It preserves every original instruction; this entrypoint
is a routing summary, not a replacement contract. Follow its linked shared
contracts for the selected task.

Read docs/guides/lifecycle-cookbook.md; Markdown packages remain draft-only until actual reviewed freeze. Report exact findings and bounded verdict; do not rewrite the audited candidate.

For new capability claims, apply the bounded pre-freeze feasibility mapping in
the linked contract: actual entrypoints, lower authority, negative case and owners.

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
`docs/reference/safe-artifact-authoring.md`.

Full contract SHA256: `bf9d49e7ef6e9e64749f1385d6b62613326d4f4aa86022cb6048c8ce7b6140fe`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.
