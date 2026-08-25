# Release 2.4.1: Workflow evidence validation

Status: `FROZEN / S2 ACCEPTED / READY_FOR_WORKER_PACKET_COMPILATION`  
Tier: `S2`  
Depends on: accepted Release 2.4

The canonical Git-visible plan package is `plans/release-2-4-1/`. The
operator-local planning mirror remains under the ignored `tasks/release-2-4/`
tree and is not package-integrity authority.

## Goal

Restore fail-closed author/reviewer separation, valid public plan schemas and typed review failures before any further feature release.

## User outcome

An omitted worker identity can no longer bypass independent review, malformed reviews fail before workflow mutation, and exported plan schemas validate against their declared JSON Schema draft.

## Scope

1. Require non-empty `actor` and `actorRunId` for a task result entering review or rework.
2. Make reviewer separation fail closed when worker identity is absent and retain same-actor and same-run rejection.
3. Require `reviewId` during review validation, before task acceptance mutates state.
4. Remove duplicate `required` entries from both plan-manifest schemas and add a registry-wide uniqueness regression test.
5. Prove that plan check and plan adoption continue to use the same completeness validator; adoption-only runtime integrity and quorum checks remain separate.
6. Publish version `2.4.1` and make Release 2.5 depend on the accepted patch.

## Non-goals

- changing accepted historical state or rewriting old evidence;
- weakening reviewer independence for compatibility;
- adding plan-lock or phase-resource CLI commands, which belong to Release 2.6;
- changing workflow authority or task-attempt semantics.

## Compatibility

Existing historical artifacts remain readable. An in-flight `agent-task-result.v2` without worker identity must be re-emitted before it can enter review; it cannot be grandfathered into acceptance.
