# Changelog

## Unreleased

- No changes yet.

## 0.2.0 - 2026-07-23

- Added provider-neutral model routing for lifecycle phases and task attempts.
- Added host-local model profile validation without storing concrete provider
  model names in portable core contracts.
- Added workflow enforcement for model-backed task attempts: `workflow
  task-result` now requires a host-attested usage receipt bound to the run,
  task, attempt, plan digest, source revision and route decision digest.
- Added fail-closed protection against critical review downgrades to `budget`
  or `local-compact` model classes.
- Updated adapter descriptors and the offline adapter baseline with
  workflow-enforced model-route execution semantics.

## 0.1.2 - 2026-07-23

- Added a live cost/token calibration profile and verifier; production
  promotion now requires real usage-attested receipts and rejects synthetic
  replay evidence.
- Added `S1-SMALL-CONTEXT-4K-STRICT-01` to the synthetic conformance corpus,
  budget targets and replay plan.
- Added the `4k-strict` compact-context window for local models and constrained hosts below the previous 8k baseline.
- Fixed `context check` and `context render` CLI overflow semantics: a rendered `FAIL` result now exits non-zero with `context-overflow`.
- Fixed compact context receipts to enforce all bundled profile budgets: reserved output, active packet, state summary, evidence summary, optional tool output, and recent verbatim user turns.
- Added CLI wiring for existing specification, plan, and task-packet compiler core checks.
- Added a required final-audit precondition to `workflow finalize` and bind the audit identity into final proof.
- Added hard controller-gate receipt enforcement for task and finalization workflow transitions.
- Added stable machine-readable neutrality error codes and JSON error envelopes for neutrality CLI helpers.
- Fixed Windows checkout line-ending stability for content-addressed synthetic
  conformance fixtures and skill metadata checks.
- Clarified the modular-controller architecture document with the current source map, implemented/reserved boundaries, and split candidates.
- Centralized workflow operation commits in a shared operation kernel used by plan adoption, run, task, and finalization transitions.
- Enforced all declared ZIP archive neutrality policy limits, including nesting, archive/entry counts, compressed/expanded byte ceilings, and compression ratio.

## 0.1.1 - 2026-07-22

- Added root-level Codex, Claude Code, and Cursor publication manifests.
- Added Codex, Claude Code, and Cursor marketplace catalogs for the tagged source package.
- Added root OpenCode source config and `skills.sh.json` metadata for Hermes-compatible skill discovery.
- Updated README installation and publication guidance for `v0.1.1`.

## 0.1.0 - 2026-07-22

- Added the standalone Agent Lifecycle Kit offline release-candidate contract.
- Added native adapter projections for Codex, Claude Code, Cursor, Hermes and OpenCode as experimental surfaces.
- Added local release-candidate assembly, verification, support-matrix and deferred-promotion checks.
