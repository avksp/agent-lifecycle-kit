---
name: agent-plan-to-workers
description: Compile a frozen reviewed plan into deterministic worker packets with dependency waves, ownership, validation, evidence, and result contracts.
---

# Agent Plan To Workers

Use this skill after a plan is reviewed and frozen. The task is compilation:
project a frozen plan into worker packets without redesigning it.

## Contract

1. Verify the plan manifest, lock, source revision, plan digest, and review
   verdict.
2. Reject unfrozen, mismatched, or stale plan inputs.
3. Build dependency waves from the frozen DAG.
4. Emit one packet per executable workstream with:
   task id, owner, reviewer, dependencies, goal, planned items, allowed writes,
   forbidden writes, read-only context, validation command ids, evidence ids,
   budget limits, result path, review path, and remediation route.
5. Emit a controller validation descriptor for controller-owned gates.
6. Keep lead-owned integration and shared seams explicit; do not smuggle them
   into worker write sets.
7. Use deterministic ordering and content-addressed packet identity.

## Rules

- Do not change requirements, acceptance criteria, write ownership, or gates.
- Do not add implementation advice that conflicts with the frozen plan.
- Do not include secrets, private keys, credentials, or host-private state.
- Keep packet context minimal: active task, referenced contracts, and exact
  evidence route.
- For compact mode, emit packets that fit the target profile or report a split
  requirement before execution.
- Fail closed if a worker cannot be assigned a complete ownership and evidence
  contract.

## Output

Return:

- packet index with frozen plan identity;
- dependency waves;
- task packet paths and digests;
- controller validation descriptor;
- unresolved compile findings, if any.
