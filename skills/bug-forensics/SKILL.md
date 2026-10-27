---
name: bug-forensics
description: Optional defect-repair profile for bug search, regression repair, flaky failure investigation, incidents, and security-bug fixes.
---

# Bug forensics

## Contract

Optional defect profile, disabled unless the reviewed task opts in. Require symptom, reproduction red before modification, same failure fingerprint, hypothesis ledger, root cause, minimal patch, green regression and canonical fix-impact evidence.

Read [the complete lifecycle contract](references/lifecycle-contract.md) before
acting in this stage. It preserves every original instruction; this entrypoint
is a routing summary, not a replacement contract. Follow its linked shared
contracts for the selected task.

Cross-check is advisory unless explicitly required by the frozen plan. Reuse existing receipts; do not create a competing bug engine or treat a recommendation as activation.

Read the [common route](../../docs/guides/lifecycle-cookbook.md#canonical-execution-route),
[recipe table](../../docs/guides/lifecycle-cookbook.md#choose-a-recipe) and
[safety rules](../../docs/guides/lifecycle-cookbook.md#safety-rules). For the opted-in repair, read
[the repair recipe](../../docs/guides/lifecycle-cookbook.md#bug-forensics-repair) and its required links, including
[the defect guide](../../docs/guides/bug-forensics-workflows.md).
Recipe selection does not activate the optional profile.

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
[safe artifact authoring](../../docs/reference/safe-artifact-authoring.md).

Full contract SHA256: `b7e281eaae2aeddb49c3d0794b60ca6384a8e1715ac496eb25f77d7e5c963add`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.

Resource paths are relative to this installed skill root. The package supplies
its required documents; a consumer project is not their fallback source.
