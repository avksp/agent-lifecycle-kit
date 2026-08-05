# Changelog

## Unreleased

- No changes yet.

## 1.39.0 - 2026-08-05

- Added `agent-lifecycle adapter task start` for adapter-specific task intake
  from text, Markdown files, frozen run requests and frozen manifests with
  workflow binding.
- Added `agent-adapter-task-start-receipt.v1` and
  `agent-adapter-task-run-request.v1` with review/freeze boundaries, raw-text
  redaction, Bug Forensics recommendations and analysis-first draft markers.
- Documented adapter task intake, updated workflow-orchestrator guidance and
  refreshed publication metadata to `1.39.0`.

## 1.38.0 - 2026-08-04

- Added managed adapter session receipts and commands for `adapter session
  start/status/resume/promote` and `adapter run`, with lineage-checked resume
  and managed workflow proof boundaries.
- Added descriptor-driven `managedLaunch` profiles for all bundled adapters and
  secure launch validation for argv arrays, `shell=False`, env allowlists,
  redaction and no native config writes.
- Documented managed session support separately from plugin installation,
  adapter maturity and progress support, and updated publication metadata to
  `1.38.0`.

## 1.37.0 - 2026-08-04

- Added opt-in progress hooks for `workflow run`, `workflow task-result`,
  `workflow task-accept` and `workflow finalize` with stderr rendering or
  `agent-progress-hook-receipt.v1` side receipts.
- Added `agent-progress-hook-policy.v1` and managed workflow proof checks so
  `AUTO` progress cannot be claimed from plugin installation alone.
- Documented managed progress hook boundaries for every adapter and updated
  publication metadata to `1.37.0`.

## 1.36.0 - 2026-08-04

- Added explicit terminal progress rendering with `agent-lifecycle report
  progress --terminal` while keeping JSON output as the default.
- Added adapter progress bridge receipts and schemas for host wrappers:
  `agent-progress-bridge-config.v1` and
  `agent-progress-bridge-receipt.v1`.
- Documented progress support levels for all adapters and updated publication
  metadata to `1.36.0`.

## 1.35.0 - 2026-08-03

- Added bounded `agent-lifecycle report progress --watch` receipts for
  host-side lifecycle progress displays without model calls or state writes.
- Added `agent-lifecycle report change-summary` to produce Git-style counters
  for files changed, insertions, deletions, modified, added and deleted.
- Documented progress bridge integration for Codex, Claude Code, OpenCode and
  other host adapters, and updated publication metadata to `1.35.0`.

## 1.34.0 - 2026-08-03

- Added structural plan completeness profiles for `S0`, `S1` and `S2`,
  including the default `profiles/plan-completeness-profile.v1.json`.
- Added `agent-lifecycle plan completeness-check` and
  `plan check --require-completeness` to produce or enforce
  `agent-plan-completeness-validation.v1` blockers.
- Documented compact-but-complete planning for small/local models and updated
  planning skills, public contracts and release publication metadata.

## 1.33.0 - 2026-08-03

- Added `agent-lifecycle audit implementation` and
  `agent-lifecycle audit final-implementation` to emit typed implementation
  audit reports from frozen plan, workflow state, task result, review,
  ownership and evidence inputs.
- Added workflow gates so plans can require accepted implementation audit
  reports before `workflow task-accept`, managed runner continuation and direct
  `workflow finalize`.
- Added public schemas and docs for implementation audit reports, final
  implementation audit aggregation and validation outputs.

## 1.32.0 - 2026-08-03

- Added `agent-lifecycle workflow run`, a read-only managed lifecycle
  step-function that validates frozen plan/state lineage and returns the next
  host-owned action.
- Added managed runner receipts and public schemas for next actions,
  fail-closed blockers and no-model-call release scans.
- Added a release validator that rejects direct model or network client imports
  in managed lifecycle runner modules.

## 1.31.0 - 2026-08-03

- Added a publication version contract and validator for package metadata,
  plugin manifests, marketplace source refs and adapter-local plugin
  projections.
- Added fail-closed checks for stale plugin versions and stale marketplace refs
  so installable plugin snapshots cannot drift behind release tags.
- Documented immutable semver publication as the default path and limited a
  floating `last` channel to opt-in source refs only.

## 1.29.1 - 2026-08-02

- Fixed plugin publication manifests so Codex, Claude Code and Cursor
  installation snapshots point at the current release tag instead of the stale
  `v1.19.0` metadata.

## 1.29.0 - 2026-08-01

- Added neutral failure classification receipts for edge-case, API-contract,
  serialization, race, permission, migration, performance, flaky-test,
  security-bug and unknown failures.
- Added failure-aware model routing with bounded progressive escalation,
  no-downgrade-after-failure protection and optional cross-check
  recommendations.
- Integrated failure and flake signals with adaptive lifecycle decisions and
  Bug Forensics gates while preserving quality floors and provider-neutral
  routing.

## 1.28.0 - 2026-08-01

- Added local outcome indexes and quality-cost signals from explicit lifecycle
  receipts without telemetry, provider/model leaderboards or required USD
  fields.
- Added advisory learning recommendations that preserve quality floors, stay
  `autoApply: false` and can feed the existing policy proposal path.
- Added `agent-lifecycle metrics outcome-index`, `quality-signals` and
  `learn-recommend` plus public contracts and docs for the learning loop.

## 1.27.0 - 2026-08-01

- Added deterministic completion gate receipts that choose `STOP`, `CONTINUE`,
  `ESCALATE`, `SPLIT` or `FOLLOW_UP` from acceptance, validation, blockers,
  final proof, risk and follow-up evidence.
- Integrated optional completion gate binding into workflow finalization so
  `STOP`/`FOLLOW_UP` decisions cannot bypass current evidence digests.
- Added `agent-lifecycle specification completion-gate`, public schemas and
  docs for stop/continue/follow-up semantics.

## 1.26.0 - 2026-08-01

- Added small-model packet compilation from frozen task packets with exact
  write scope, compact context receipts and required output contracts.
- Added fail-closed small-model output validation for missing fields, digest
  drift, production-promotion claims and changed files outside write scope.
- Added `agent-lifecycle task compile-small` and documented small/local model
  limits, including adaptive quality-floor eligibility.

## 1.25.0 - 2026-08-01

- Added adaptive lifecycle policy decisions that choose the lightest safe mode
  from neutral task, risk, evidence and resource inputs.
- Added schema-backed quality-floor and adaptive-decision receipts with digest
  validation, advisory-by-default behavior and opt-in automatic selection.
- Integrated lifecycle mode/floor hints with provider-neutral model routing
  while keeping currency metadata metered-only and unused for core selection.

## 1.24.0 - 2026-08-01

- Added draft-only issue-to-spec intake for external tickets and tracker
  payloads without execution or freeze authority.
- Added read-only workflow event feed and lifecycle progress projections with
  fixed-width one-line rows, attested token counters and git-style change
  summaries.
- Added advisory adapter package discovery for release inspection without
  descriptor override, maturity promotion or live host calls.

## 1.23.0 - 2026-08-01

- Added metered-only `meteredAskThreshold` advisory validation without changing
  hard cap behavior or requiring currency fields for local/subscription modes.
- Added optional runtime policy receipts that distinguish proven
  pre-execution enforcement from advisory-only logging.
- Added provider-neutral cross-check independence evidence and worktree
  write-back receipts for isolated overlay apply/discard decisions.

## 1.22.0 - 2026-08-01

- Added release-time adapter capability bench tools that generate bounded probe
  plans from capability manifests and validate live receipts for drift without
  promoting adapter maturity.
- Extended sandbox receipt validation for partial process containment and
  redacted credential proxy boundaries inside `agent-sandbox-receipt.v1`.
- Updated live-promotion runbooks, support matrices and public contract docs
  for capability bench and sandbox-boundary evidence.

## 1.21.0 - 2026-08-01

- Added draft-only task templates for bugfix, idea-to-PR, PR review,
  merge-conflict repair and release-readiness workflows.
- Added reusable Bug Forensics recipes that reference existing receipts instead
  of defining a competing bug-fix evidence chain.
- Added optional quality CLI commands for template and recipe listing/checking.

## 1.20.0 - 2026-08-01

- Added a generic external dialect import framework with explicit
  family/profile selection for workflow-like and agent/harness-like inputs.
- Added workflow-family and agent-family draft mappers that keep imported
  content untrusted, require review/freeze, never execute imported workflow
  nodes and keep provider/model/auth/tool hints host-local and redacted.
- Added CLI commands for external import profile listing, generic external
  imports and external import validation.

## 1.19.0 - 2026-08-01

- Promoted Pi to host-specific `VERIFIED` for Pi 0.83.0 on the tested
  host-local provider/model binding.
- Added a bounded Pi JSONL live harness on the shared JSON CLI receipt loop,
  with no-session, no-tools, no project-local context, offline startup and
  clean-worktree checks.
- Added Pi install/preflight containment, live conformance, live calibration
  and lifecycle proof evidence summaries without public directory or
  production promotion claims.

## 1.18.0 - 2026-08-01

- Promoted OpenInterpreter to host-specific `VERIFIED` for `interpreter`
  0.0.34 on the tested host-local provider/model binding.
- Added a bounded OpenInterpreter JSONL live harness on the shared JSON CLI
  receipt loop, including preflight containment, read-only sandbox invocation,
  clean-worktree checks and token/resource usage receipts.
- Added provider-neutral host env injection for live harnesses through explicit
  operator allowlists and redacted `agent-host-env-file-redacted.v1` metadata.
- Added host-env hygiene validation and separated the release security check
  from the live harness implementation.

## 1.17.0 - 2026-07-31

- Promoted Grok Build to host-specific `VERIFIED` for Grok Build 0.2.117 on
  the tested host-local provider/model binding.
- Added a bounded Grok Build live harness on the shared JSON CLI receipt loop,
  with plan-mode containment, disabled subagents/memory/web search and
  clean-worktree checks.
- Added Grok Build live host conformance, live calibration, positive ACP probe,
  containment and lifecycle proof evidence summaries without public directory
  or production promotion claims.
- Recorded the adapter harness DRY audit and left migration of older VERIFIED
  harnesses to a parity-fixture hardening release.

## 1.16.0 - 2026-07-31

- Promoted Goose to host-specific `VERIFIED` for Goose 1.45.0 on the tested
  host-local provider/model binding.
- Added a bounded no-session/no-profile Goose live harness and shared JSON CLI
  receipt loop for future adapter promotions.
- Added Goose live host conformance, live calibration, containment and
  lifecycle proof evidence summaries without public directory or production
  promotion claims.
- Added Goose to live calibration and adapter baseline profiles and recorded a
  staged DRY audit for existing large live harnesses.

## 1.15.0 - 2026-07-31

- Completed adapter inventory and promotion-gate coverage for all 12 adapter
  descriptors.
- Added Goose to root, English and Russian adapter lists and install docs.
- Added redacted EXPERIMENTAL evidence summaries for Goose, Grok Build,
  OpenInterpreter and Pi without claiming live promotion.
- Tightened docs, support-matrix and evidence-index validators so secondary
  adapters cannot be omitted from release gates.

## 1.14.0 - 2026-07-31

- Added optional Bug Forensics / Defect Repair profile contracts and helpers.
- Added reproduction-before-modification, failure fingerprint, hypothesis
  ledger, regression-proof, workflow gate and audit receipts.
- Reused `agent-fix-impact-receipt.v1` for no-collateral-damage evidence and
  `agent-cross-check-receipt.v1` for explicit high-risk bug cross-checks.
- Added English and Russian Bug Forensics documentation and compact-context
  budget guidance.

## 1.13.0 - 2026-07-31

- Added EXPERIMENTAL Grok Build, OpenInterpreter and Pi adapter descriptors,
  capability manifests and offline conformance fixtures.
- Added a negative Grok ACP-probe fixture so failed local discovery produces
  explicit fail-closed evidence.
- Extended the offline adapter baseline and fixture index for the secondary
  adapters while keeping live promotion unclaimed.
- Added adapter documentation and support-matrix entries for the secondary
  adapters.

## 1.12.0 - 2026-07-31

- Added runner recovery receipts for attempt snapshot, restore, abandon and
  selected-attempt metadata.
- Added worker lease and heartbeat receipts that distinguish active, expired
  and completed workers.
- Added optional cross-check profile and receipts with token/resource budget
  caps, disabled-by-default activation and plan-gated blocking use.
- Added phase resource measurements that reuse the usage-export envelope for
  tokens, durations and resource counters without mandatory USD-cost fields.
- Added English and Russian documentation for runner recovery and cross-check
  behavior.

## 1.11.0 - 2026-07-31

- Added import dialect profiles for Constitution/ADR and AGENTS/agentskills
  inputs while keeping imported artifacts untrusted DRAFTs.
- Added `nativeDialectProfileDigest` provenance on planning import results and
  candidate plan import state.
- Added rebuildable episode indexes and bounded episode retrieval with
  `chainVerified` or `chainUnchecked` provenance.
- Added English and Russian documentation for import mappers and episode
  retrieval.

## 1.10.0 - 2026-07-31

- Added sandbox-boundary contracts for runtime filesystem, network, process,
  environment and enforcement-source evidence.
- Added sandbox receipt builders, validators and fail-closed workflow policy
  checks for high-risk or explicitly sandbox-required tasks.
- Added additive adapter sandbox capability declarations without overclaiming
  verified OS sandbox support.
- Added English and Russian sandbox-boundary documentation and public contract
  references.

## 1.9.0 - 2026-07-31

- Added proof-integrity contracts for stable finding identity, root-cause
  evidence, canonical fix-impact receipts and append-only receipt hash chains.
- Added proof-integrity validation helpers and optional finalization binding
  through `workflow finalize --proof-integrity`.
- Added hash-chain migration policy for new runs and explicit legacy
  exemptions/backfill behavior.
- Added English and Russian evidence-integrity documentation.

## 1.8.0 - 2026-07-31

- Added schema-backed usage/session export reports with receipt digests,
  tokens, steps, resources, durations, adapter ids and budget decisions.
- Added `agent-lifecycle metrics usage-export` with deterministic JSON and
  table output.
- Kept `cost_usd` optional and host-reported only; local model usage remains
  token/resource based.
- Added redaction checks and usage export documentation.

## 1.7.0 - 2026-07-31

- Added schema-backed neutral host capability declarations for ACP support.
- Added fail-closed ACP probe receipts that do not start live model calls.
- Added an EXPERIMENTAL Goose adapter descriptor, capability manifest,
  validation tests and adapter documentation.

## 1.6.0 - 2026-07-30

- Added read-only lifecycle policy proposals built from recommendation reports
  and regression signals.
- Added `agent-lifecycle policy tune` with explicit `--apply --output` policy
  artifact writes and compact proposal summaries.
- Added fail-closed safeguards for invalid recommendations, low-confidence
  recommendations, protected downgrades and blocking regression signals.
- Added public contracts for policy proposals, tuned policy artifacts, apply
  receipts, tune results and regression signal summaries.

## 1.5.0 - 2026-07-30

- Added advisory lifecycle mode recommendations from accumulated cost reports,
  task-shape baselines and risk floors.
- Added `agent-lifecycle metrics recommend` with write-once full output and
  compact summary output for small-context review.
- Added fail-closed baseline validation so weak or invalid statistics cannot
  lower the required lifecycle quality floor.
- Added public contracts for lifecycle baselines, overhead statistics,
  recommendations and compact recommendation summaries.

## 1.4.0 - 2026-07-30

- Added deterministic lifecycle cost report generation from explicit JSON
  artifacts with source digests, lineage, usage-confidence accounting and a
  compact summary for small-context review.
- Added `agent-lifecycle metrics cost-report` for write-once report generation
  plus validation through the existing cost-check rules.
- Kept manually authored lifecycle cost reports compatible with
  `metrics cost-check`.
- Split the built-in schema registry into smaller domain modules while keeping
  `schema list/show` compatibility.
- Split safe host inspection probes by adapter so `inspection.py` stays a small
  public dispatcher.

## 1.3.0 - 2026-07-30

- Compact root README and Russian README into navigable entry points while
  moving detailed setup and command reference material into dedicated docs.
- Added quickstart, adapter install, CLI reference, and source-of-truth
  documentation.
- Improved readiness diagnostics so tracked redacted adapter evidence summaries
  are reported separately from host-local raw receipts.

## 1.2.0 - 2026-07-30

- Added optional evidence index contracts and `agent-lifecycle evidence
  index/search` for compact, rebuildable summaries over validated artifacts.
- Added untrusted planning input import contracts and `agent-lifecycle import
  plan/check` so imported work remains draft-only until ALK review and freeze.
- Added reviewed skill improvement proposal validation without automatic skill
  edits.

## 1.1.0 - 2026-07-30

- Added optional plan continuity contracts for repository-reference validation,
  immutable frozen-plan snapshots, snapshot reconciliation and compact reviewer
  handoff packets.
- Added `agent-lifecycle plan refs-check/snapshot/reconcile/handoff`.
- Added documentation for team-scale planning continuity while keeping
  single-repository lifecycle behavior unchanged by default.

## 1.0.0 - 2026-07-30

- Stabilized public schema and CLI JSON compatibility policy with
  `agent-lifecycle contract policy/check`.
- Added lifecycle cost validation with separate implementation, product
  validation, pipeline compliance and coordination categories.
- Added resource/security guidance and release security tests for local-path
  leakage, secret markers and host-bound adapter claims.
- Updated package and plugin metadata to stable `1.0.0`.

## 0.19.0 - 2026-07-30

- Added optional quality pack validation and fixture-based behavior checks for
  concrete lifecycle outcomes.
- Added redacted diagnostic bundle export from existing evidence artifacts.
- Added compact read-only status views for small local models without changing
  source-of-truth evidence.

## 0.18.0 - 2026-07-30

- Added neutral adapter event capture declarations, event stream receipts and
  conformance checks for declared event producers.
- Added negative coverage for hidden failed commands and false completion
  claims in adapter event streams.
- Added structured review verdict validation with separate requirement fit,
  implementation quality, evidence quality and residual risk dimensions.

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
  1.18.9 with host-local live host conformance, usage calibration, and full
  ALK lifecycle proof evidence.
- Promoted the Hermes adapter to host-specific `VERIFIED` for Hermes Agent
  v0.19.0 with host-local live host conformance, usage calibration, and full
  ALK lifecycle proof evidence.
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
- Added release 0.4 validation for Cursor host-local compatibility shape, negative
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
  tracked tests no longer depend on ignored `work/**` planning artifacts.
- Added placeholder-safe adapter tests for Cursor experimental metadata.

## 0.1.1 - 2026-07-23

- Added release assembly, inventory, verification, and support-matrix evidence
  tooling for source release candidates.
- Added release CI matrix profile validation and deferred promotion contracts.

## 0.1.0 - 2026-07-22

- Initial source release with provider-neutral lifecycle skills, workflow
  contracts, adapter descriptors, and baseline validation tooling.
