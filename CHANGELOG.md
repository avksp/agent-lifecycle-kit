# Changelog

## Unreleased

- Added the `4k-strict` compact-context window for local models and constrained hosts below the previous 8k baseline.
- Fixed `context check` and `context render` CLI overflow semantics: a rendered `FAIL` result now exits non-zero with `context-overflow`.
- Added CLI wiring for existing specification, plan, and task-packet compiler core checks.
- Added a required final-audit precondition to `workflow finalize` and bind the audit identity into final proof.

## 0.1.1 - 2026-07-22

- Added root-level Codex, Claude Code, and Cursor publication manifests.
- Added Codex, Claude Code, and Cursor marketplace catalogs for the tagged source package.
- Added root OpenCode source config and `skills.sh.json` metadata for Hermes-compatible skill discovery.
- Updated README installation and publication guidance for `v0.1.1`.

## 0.1.0 - 2026-07-22

- Added the standalone Agent Lifecycle Kit offline release-candidate contract.
- Added native adapter projections for Codex, Claude Code, Cursor, Hermes and OpenCode as experimental surfaces.
- Added local release-candidate assembly, verification, support-matrix and deferred-promotion checks.
