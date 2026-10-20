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

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
`docs/reference/safe-artifact-authoring.md`.

Full contract SHA256: `ca29a0ffe9bc3f0418232d71dc1199f553ef46c1d155ce0f0d9938c889aadc0f`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.
