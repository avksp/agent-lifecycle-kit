# Release 2.6: Operator CLI and release accounting

Status: `FROZEN / REVISION 6 / S2 ACCEPTED / LOCK PENDING`  
Tier: `S2`  
Depends on: accepted Release 2.5

## Goal

Remove operator dead ends and make lifecycle time/token accounting comparable without inventing missing telemetry or weakening required work.

## User outcome

Operators can create and verify a final reviewed plan lock, build a phase-resource measurement, and produce one release-level accounting artifact through bounded CLI commands. The accounting output distinguishes measured, estimated, time-window-only and unavailable data.

## Scope

1. Expose the existing `build_plan_lock_v2` API through a reviewed no-replace CLI boundary restricted to a `FROZEN` manifest and an independent `READY_TO_FREEZE` review bound to the same package, revision and exact finalized manifest digest.
2. Restrict lock output to the manifest's canonical `planArtifactRoot/plan.lock.json`, then verify the created lock and complete declared package inventory before returning success.
3. Expose `build_phase_resource_measurement` as a bounded CLI operation with an exact `generatedBy` route and validation output.
4. Expose release-accounting generation and validation through `metrics release-accounting` using only explicit bounded source artifacts.
5. Make lifecycle cost collection understand phase-resource measurements instead of estimating tokens from their JSON byte size.
6. Define release accounting with separate ALK-process, implementation, audit and post-audit-remediation views while retaining the canonical cost categories underneath.
7. Represent elapsed wall time, reviewer compute, parallel/non-additive intervals, source scope, telemetry status and ALK/plugin/controller version provenance explicitly.
8. Document phase-separated sessions using existing task packets, snapshots, checkpoints and handoffs; do not add a second context system.

## Non-goals

- estimating missing model usage or converting `UNAVAILABLE` to zero;
- deriving money from a provider price table;
- combining authorization, freeze, execution and acceptance into one command;
- creating a lock from self-declared status without an independently bound review;
- changing workflow authority or reducing validation for a target process ratio;
- setting optimization percentage targets before Release 2.6 establishes a real comparable baseline.

## Freeze ordering

Revision 6 retains the review self-reference solution and closes the revision-5 publication ownership and evidence-precision findings:

1. finalize the manifest bytes with `status: FROZEN`, `planReview.report` and the review path already present in `planFiles`;
2. keep the declared review file absent while independent S2 reviews those exact manifest bytes;
3. write the accepted review into the pre-declared `plan-review-r6.json` path with `reviewedPlanHash` equal to the unchanged manifest digest;
4. re-run structural and review-binding checks;
5. create `plan.lock.json` last and verify the complete filesystem inventory.

The missing review and lock keep the candidate non-executable during steps 1-2. No review-neutral digest normalization is permitted.

Revision 6 also gives WS26-03 ownership of both install guides required by the 2.6.0 publication pins, fixes the exact phase bound at 256, requires a dedicated lock-command helper to preserve the dispatch complexity gate, and names `tests/planning/test_continuity.py` as the tracked handoff fixture.
