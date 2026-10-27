---
name: agent-plan-to-workers
description: Compile a frozen reviewed plan into deterministic worker packets with dependency waves, ownership, validation, evidence, and result contracts.
---

# Agent plan to workers

## Contract

Compile only the exact independently reviewed frozen manifest and lock. Keep task ownership, DAG, acceptance, evidence, forbidden paths and budgets unchanged; reject stale inputs. Compilation grants no execution permission.

Read [the complete lifecycle contract](references/lifecycle-contract.md) before
acting in this stage. It preserves every original instruction; this entrypoint
is a routing summary, not a replacement contract. Follow its linked shared
contracts for the selected task.

Use task compile with a separate runtime output root. Packet rendering must preserve the complete task contract and bounded context.

Packet compilation has no cookbook recipe. Use the complete role contract
and the frozen packet inputs; do not substitute an execution recipe.

Do not bypass independent review, reviewed freeze, ownership, authorization or
budgets. Missing evidence stays missing; unknown telemetry stays null. Do not
reset expenses or run clocks after retries or context compaction.

Safe artifact commands: `task artifact-create` creates new bounded structured
JSON; `task artifact-inspect` displays it read-only. Serialization and prepared
Review Mesh packets grant no review, attestation or execution authority. See
[safe artifact authoring](../../docs/reference/safe-artifact-authoring.md).

Full contract SHA256: `f7d34afc28c907d002dd7fdef926309458403eeb6a017d46bd1360c5cf07f0d5`
Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`.

Resource paths are relative to this installed skill root. The package supplies
its required documents; a consumer project is not their fallback source.
