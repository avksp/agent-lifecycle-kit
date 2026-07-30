# Changelog

## Unreleased

- No changes yet.

## 0.17.0 - 2026-07-30

- Added schema-backed follow-up registers with validation, close results and
  compact summaries for postponed or externally blocked work.
- Added `agent-lifecycle followup check/add/close/sweep` and optional
  `workflow finalize --follow-up-register` blocking for open items that
  contradict current acceptance or completion proof.
- Added worktree isolation policy and attempt receipt contracts plus
  `agent-lifecycle worktree policy-check/receipt/check`.

## 0.16.0 - 2026-07-30

- Added provider-neutral runner state, policy, transition request/result and
  compact snapshot contracts.
- Added `agent-lifecycle runner start/status/transition/stop/resume` commands
  for bounded execution-loop control without replacing workflow state.
- Added attempt, reroute, split, token-budget and patch write-scope guards plus
  architecture docs for future worktree and host-event integration.

## 0.15.0 - 2026-07-30

- Added schema-backed goal records for binding user intent, owner-visible
  outcome, constraints, evidence ids and workflow lineage across long tasks.
- Added compact objective snapshots plus `agent-lifecycle goal check`,
  `goal summarize` and `goal update` commands for low-token continuation
  without replacing workflow state.
- Added optional `workflow finalize --goal-record` proof binding and
  fail-closed validation for stale, mismatched or contradictory goal records.

## 0.14.0 - 2026-07-30

- Added `completionCheck` support for specifications, plan adoption and final
  proof generation.
- Added `agent-completion-check.v1` and
  `agent-completion-check-receipt.v1` schemas with fail-closed finalization
  when a declared completion check is missing or reports `FAIL`.
- Replaced the older synthetic replay quality key with `qualityCheck` and
  added regression coverage to keep copied terminology out of tracked source.

## 0.13.0 - 2026-07-30

- Added `agent-lifecycle diagnose` for one redacted readiness report covering
  checkout state, package version, compact-context and model-routing profiles,
  adapter descriptor validation, safe inspection status, and local evidence
  availability.
- Added `agent-lifecycle adapter install-plan` for dry-run host setup plans
  that preview files, commands and operator actions without writing host
  configuration or changing adapter maturity.
- Added schemas, tests, and documentation for readiness diagnostics and
  promotion-safe setup planning.

## 0.12.4 - 2026-07-29

- Hardened Gemini CLI headless live commands with `--skip-trust` so clean
  worktree canaries fail on real host/auth blockers instead of workspace trust.
- Corrected Kimi Code headless live commands by removing the incompatible
  `--plan` flag and adding post-invocation clean-worktree checks.
- Recorded current non-promotion blockers: Gemini CLI is blocked by the current
  unsupported Gemini Code Assist client tier, and Kimi Code is blocked until a
  provider/model alias is configured.

## 0.12.3 - 2026-07-29

- Added bounded Gemini CLI and Kimi Code runners plus live harnesses for
  `stream-json` receipt normalization while keeping both adapters
  `EXPERIMENTAL`.
- Updated adapter projection manifests, README, Russian README, support matrix,
  validation docs, and release inventory checks for the new harness files.
- Confirmed Gemini CLI 0.46.0 and Kimi Code 0.30.0 safe preflight without live
  model calls; live conformance, calibration, and lifecycle proof remain
  required before any `VERIFIED` promotion.

## 0.12.2 - 2026-07-29

- Promoted the OpenCode adapter to host-specific `VERIFIED` for OpenCode CLI
  1.18.9 with GLM 5.2 live host conformance, usage calibration, and full ALK
  lifecycle proof evidence.
- Promoted the Hermes adapter to host-specific `VERIFIED` for Hermes Agent
  v0.19.0 with GLM 5.2 live host conformance, usage calibration, and full ALK
  lifecycle proof evidence.
- Promoted the Qwen Code adapter to host-specific `VERIFIED` for Qwen Code
  0.21.0, added the bounded Qwen Code runner and live harness, and synchronized
  adapter docs, support matrix checks, and package metadata to `0.12.2`.

## 0.12.1 - 2026-07-29

- Fixed Windows CI path separator handling in the adapter scaffold CLI test.
- Updated package metadata and source-release documentation from `v0.6.1` to
  `v0.12.1`.
- Updated Codex, Claude, Cursor, Hermes and marketplace plugin metadata to the
  same `0.12.1` patch version.

## 0.12.0 - 2026-07-29

- Added the Kimi Code adapter scaffold, Kimi Code 0.30.0 safe inspection
  evidence, and explicit live-harness blocker while keeping Kimi Code
  `EXPERIMENTAL`.
- Expanded support-matrix validation to all tracked host rows.

## 0.11.0 - 2026-07-29

- Added the Qwen Code adapter scaffold, Qwen Code 0.21.0 safe inspection
  evidence, and explicit live-harness/resource-cap blockers while keeping
  Qwen Code `EXPERIMENTAL`.

## 0.10.0 - 2026-07-29

- Added the Gemini CLI adapter scaffold, Gemini CLI 0.46.0 safe inspection
  evidence, and explicit live-harness blocker while keeping Gemini CLI
  `EXPERIMENTAL`.

## 0.9.0 - 2026-07-29

- Added Cursor Agent 2026.07.23 safe inspection/preflight evidence and explicit
  Free-tier non-promotion blocker while keeping Cursor `EXPERIMENTAL`.

## 0.8.0 - 2026-07-29

- Added Hermes v0.19.0 safe inspection/preflight evidence and explicit
  non-promotion blocker while keeping Hermes `EXPERIMENTAL`.

## 0.7.0 - 2026-07-29

- Added adapter capability manifests, manifest validation helpers, and receipt
  normalization/redaction helpers for future host adapter work.
- Added `agent-lifecycle adapter inspect` for safe descriptor and host
  capability discovery without live model invocation or promotion claims.
- Extended adapter scaffold output with capability manifests, fail-closed runner
  skeletons, receipt normalizers, adapter test skeletons, and support stubs.
- Added offline adapter conformance verification and OpenCode 1.18.9 safe
  inspection evidence while keeping OpenCode `EXPERIMENTAL`.

## 0.6.1 - 2026-07-29

- Added reusable live-promotion and verified-adapter release checklists.
- Extended adapter scaffold output with projection manifest, event bridge
  placeholder, and validation instructions for future hosts.
- Generalized the support-matrix maturity gate to bind each `VERIFIED` host row
  to its adapter descriptor evidence markers and added a missing-evidence
  regression test.

## 0.6.0 - 2026-07-29

- Promoted the Codex adapter to host-specific `VERIFIED` for Codex CLI 0.145.0
  with local live host conformance, live calibration, and full ALK lifecycle
  proof evidence.
- Made Codex live harness invocations ephemeral so release probes do not leave
  reusable host session state.

## 0.5.0 - 2026-07-29

- Added release-0-5 lifecycle gates for frozen acceptance checklist validation,
  neutral adapter event streams, write-scope-enforced task acceptance,
  per-attempt baseline reconciliation, external-action parking, and final
  completion signals.
- Promoted the Claude Code adapter to host-specific `VERIFIED` for Claude Code
  2.1.220 with local live host conformance, live calibration, and full ALK
  lifecycle proof evidence.
- Updated package, plugin, marketplace, support-matrix, release-note, and
  install references for `v0.5.0`.

## 0.4.0 - 2026-07-28

- Added host-local model selection profiles and redacted model-selection
  receipts for live host harnesses.
- Added budget decision workflow controls for manual pause and bounded
  auto-reroute after budget or resource-cap exhaustion.
- Split the root CLI dispatcher into thin entrypoint, parser, and dispatch
  modules.
- Added release 0.4 validation for Cursor GLM compatibility shape, negative
  suite coverage, context-fit evidence, and portable provider-model leakage.
- Updated live host and production-promotion documentation for metered,
  subscription, and local budget modes.

## 0.3.0 - 2026-07-28

- Added release 0.3 proof hardening: final-candidate verification now parses
  required evidence, validates schema/status semantics, and checks workflow
  lineage through the shared core checker.
- Added release 0.3 task-packet context-fit and negative-suite coverage
  verifiers.
- Added host adapter descriptor validation through the provider-neutral
  `HostOperationRequest` and `HostOperationReceipt` contracts.
- Added live host conformance receipt validation for future `VERIFIED`
  promotion gates.
- Added `py.typed` packaging metadata and a packaging smoke evidence runner.

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

- Removed archived release tarballs and zip files from the source tree and
  blocked future archive commits through release inventory validation.
- Added a clean-checkout CI simulation script and CI regression coverage so
  tracked tests no longer depend on ignored `tasks/**` planning artifacts.
- Added placeholder-safe adapter tests for Cursor experimental metadata.

## 0.1.1 - 2026-07-23

- Added release assembly, inventory, verification, and support-matrix evidence
  tooling for source release candidates.
- Added release CI matrix profile validation and deferred promotion contracts.

## 0.1.0 - 2026-07-22

- Initial source release with provider-neutral lifecycle skills, workflow
  contracts, adapter descriptors, and baseline validation tooling.
