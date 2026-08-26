# Release 2.5: Bounded external tool jobs

Status: `FROZEN / REVISION 10 / S2 ACCEPTED / READY_FOR_EXECUTION`  
Tier: `S2`  
Depends on: accepted Release 2.4.1

Target: `2.5.0`.

## Goal

Represent optional asynchronous external-tool work as bounded jobs and hashed artifact results without adding provider clients to ALK core.

## User outcome

Specialized tools can contribute verifiable artifacts while process, time, cost, output and trust boundaries remain explicit.

## Activation condition

Two independent projects demonstrated asynchronous lifecycle gaps beyond the synchronous external-check contract from Release 1.88:

- cancelled wrappers left child auditor processes alive, and a later run mixed output into the same files;
- nested child audits exceeded a bounded wait and returned no consolidated verdict, while their time and token use still required accounting.

The bounded evidence and source digests are recorded in `activation-evidence.md`.

## Scope

1. Define external-tool job request, status and result contracts with QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED and EXPIRED states.
2. Require adapter-owned process or network execution with explicit time, attempt, output, artifact, cost and cancellation limits.
3. Store only bounded metadata, media type, size, digest and controlled locator for generated artifacts.
4. Qualify each adapter operation with success, timeout, cancellation, process-group cleanup, terminal-parent cancellation of all declared child jobs, post-cancel write rejection, replay, stale result, oversized artifact and no-final-verdict scenarios.
5. Document bounded external-tool jobs in English and Russian with one neutral adapter example.
6. Keep synchronous one-shot checks on the Release 1.88 path and make ordinary workflows allocate no job state.

## Non-goals

- adding provider-specific network clients to the core
- embedding media or large tool output in lifecycle state
- creating a general task queue or daemon
- resuming an interrupted process or reusing its artifact namespace; recovery starts a new immutable attempt
- granting external jobs lifecycle authority

## Release boundary

This canonical tracked package is independently audited and frozen. Execution still requires explicit ALK adoption and authorization; the lock grants no provider support or production-promotion claim. English and Russian product documentation remain required implementation artifacts.
