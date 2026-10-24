---
name: agent-workflow-orchestrator
description: Run or resume the full lifecycle from request clarification through reviewed planning, freeze, authorized execution, per-task audits, and final proof.
---

# Agent workflow orchestrator

## Lifecycle

Follow clarification → planning → independent plan review → reviewed freeze → separate execution authorization → bounded tasks → independent task audits → final audit → finalize. Use atomic commands and actual native state; a goal or prose approval is not a state transition. Preserve research-only and Markdown plan review boundaries.

Read [the complete lifecycle contract](references/lifecycle-contract.md) before
acting in this stage. It preserves every original instruction; this entrypoint
is a routing summary, not a replacement contract. Follow its linked shared
contracts for the selected task.

Read the common route, recipe table and safety rules in
docs/guides/lifecycle-cookbook.md. Select the recipe for the current request
and stage. Read that recipe and its required links before acting. Load another
recipe when the stage changes. The complete lifecycle contract remains required.
Retain valid evidence after overruns; preserve all expenses and UNKNOWN usage
across retries and compact. Start only the selected frozen task.

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
`docs/reference/safe-artifact-authoring.md`.

Full contract SHA256: `b3ec79e0280c06fa1057845ce7cae24f87682a0662d6f670e79d98ee2406bc35`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.


## Existing host and continuation routes

Keep the frozen plan and lock authoritative. Adapter levels GUIDANCE_ONLY,
OBSERVED and ENFORCED describe the qualified host-owned pre-action boundary;
NO_RECOMMENDATION stays unqualified. A prompt, skill or fixture cannot create
host enforcement. Read the complete reference for the required receipts.

`workflow continue` projects first; apply only the projected revision and action.
It replaces no validator or transition. Use context checkpoint and the thread
bridge only through their existing bounded, lineage-checked contracts; restored
context grants no execution authority.
