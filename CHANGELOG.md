# Changelog

## Unreleased

- No changes yet.

## 1.89.0 - 2026-08-24

- Added provider-neutral structured-result capability contracts bound to the
  operation, adapter descriptor, host version, model class and capability
  manifest.
- Added fail-closed required-schema selection, deterministic output validation
  and a separate two-attempt structured-result repair limit.
- Added advisory 5x2x5x2 reference-task qualification with positive, boundary
  and malformed-output evidence; qualification cannot accept workflow tasks or
  adopt routes automatically.
- Added bilingual documentation and synchronized package/plugin metadata.

## 1.88.0 - 2026-08-24

- Added provider-neutral external verification contracts for bounded findings,
  tool/configuration identity, source snapshots and plan/lock lineage.
- Added optional shell-free profiles for import boundaries, module dependencies
  and declared dependencies without adding analyzer packages to runtime.
- Added fail-closed handling for unavailable, incomplete or source-drifting
  checks; external results remain non-authoritative review evidence.
- Added bilingual documentation and synchronized package/plugin metadata.

## 1.87.0 - 2026-08-24

- Added bounded adapter action evidence to the existing event stream, binding
  requests, operations, profiles, capabilities, permission decisions and safe
  result links without storing prompts or model reasoning.
- Added read-only `project profile explain` with field-level provenance,
  frozen-plan constraints and fail-closed descriptor/capability lineage.
- Added operation-specific capability-level validation and qualification
  evidence that cannot self-promote synthetic fixtures to enforcement.
- Added bilingual documentation and synchronized package/plugin metadata.

## 1.86.0 - 2026-08-24

- Added a read-only finding-to-check binding with accepted plan-delta lineage,
  bounded check identity and explicit owner and source revision.
- Added authorized, idempotent `PROPOSED` to `VERIFIED` lifecycle transitions
  with explicit retirement and fail-closed negative cases.
- Added CLI routes and bilingual documentation for advisory proposals,
  acceptance, read-only evidence and verification.
- Added regression coverage proving that finding checks cannot claim execution,
  production promotion or authority outside the existing lifecycle gates.

## 1.85.0 - 2026-08-24

- Added a canonical, offline HTTP(S) public-locator contract with bounded
  length, normalized hosts, and rejection of unsafe schemes and credentials.
- Applied the shared locator normalization and redaction behavior across
  research, evidence-index, adapter, Review Mesh, host receipt and context
  evidence surfaces.
- Added adversarial coverage for local paths, URL credentials, sensitive query
  values, fragments, mixed encodings and overlong locators.
- Added bilingual documentation and synchronized package/plugin metadata.

## 1.84.0 - 2026-08-24

- Made durable workflow state the only lifecycle authority; controlled runner
  output is retained as deprecated, journal-only compatibility evidence.
- Added shared action catalog validation for workflow projections, host gates
  and runner compatibility commands.
- Added runner budget and authorization bounds, transition regression checks
  and a standard-library-only runtime import gate.
- Updated bilingual documentation and synchronized package/plugin metadata.

## 1.83.0 - 2026-08-24

- Added exact-lineage execution authorization and a distinct non-executable
  `PLAN_ONLY` workflow phase.
- Added public external-action pause/resume routes with receipt-bound replay
  and source-lineage checks.
- Added typed run, task, plan and external blockers with explicit recovery
  routes and coherent budget split/abort transitions.
- Added the canonical final-audit outcome route for `ACCEPTED`, `REWORK`,
  `CONTRACT_CHANGE` and `BLOCKED`, preserving prior attempt evidence and
  enforcing frozen retry budgets.
- Updated bilingual workflow, CLI, architecture, skill and publication
  documentation and synchronized package/plugin metadata.

## 1.82.0 - 2026-08-24

- Added the `agent-workflow-state.v4` contract with explicit private state
  initialization and fail-closed v3 migration.
- Made task review, remediation and terminal outcomes task-local so parallel
  tasks no longer change the run into an incompatible review phase.
- Added the canonical `workflow task-review-apply` route for ACCEPTED,
  REWORK, CONTRACT_CHANGE and BLOCKED outcomes while preserving attempt
  evidence and operation idempotency.

## 1.81.1 - 2026-08-24

- Preserved ordinary HTTP(S) evidence URLs during shared redaction while
  retaining local-path, file-URI, bearer and standalone-token protection.
- Added redaction for URL userinfo credentials and sensitive query values with
  substitution-accurate counters across research and receipt surfaces.
- Updated package, plugin, marketplace and installation metadata for the
  1.81.1 patch release.

## 1.81.0 - 2026-08-23

- Added `workflow task-rework` for authorized, bounded remediation after an
  independent review or implementation audit returns `REWORK`.
- Added immutable attempt history that preserves prior result, review and audit
  identities while the next `task-start` opens a new attempt.
- Added Git-backed task snapshots and freshness checks for task results and
  implementation audits, including full-worktree ownership validation.
- Added explicit remediation policy validation and retry budgets from 2 through
  10 attempts.
- Added synchronized English and Russian documentation for the complete
  result, review, rework, new-attempt and acceptance path.

## 1.80.0 - 2026-08-22

- Added optional provider-neutral adapter lifecycle control with explicit
  `GUIDANCE_ONLY`, `OBSERVED` and `ENFORCED` levels for observable operations.
- Added pre-action, post-action and stop boundaries that can bind adapter work
  to a frozen ALK plan without claiming access to private model reasoning.
- Added exact host-version and operation qualification rules; declarations,
  prompts, plugins and offline fixtures do not promote an adapter to an
  enforced level.
- Kept the feature off by default, with no automatic host-setting changes and
  honest bundled-adapter status: `GUIDANCE_ONLY`, `NO_RECOMMENDATION` and
  `WRAPPER_ONLY` managed launch.
- Added synchronized English and Russian documentation, adapter-level status
  pages, publication metadata and deterministic documentation checks.

## 1.79.0 - 2026-08-22

- Added the canonical `agent-plan-manifest.v1` contract and deterministic
  requirement, acceptance, evidence and final-gate traceability checks.
- Added strict literal authority paths that reject glob-like, absolute,
  traversal and URI-like ownership entries before state mutation.
- Added read-only `agent-lifecycle plan verify` with lock-backed package
  integrity, workflow-state requirements and structured handoff evidence.
- Routed plan adoption, managed execution and imported planning inputs through
  the same manifest and completeness checks before they can write state.
- Added synchronized English and Russian documentation for plan verification,
  reviewer handoff and the boundary between ALK, the host and the model.

## 1.78.0 - 2026-08-22

- Added revision-bound performance budgets and deterministic evidence for CLI
  startup, neutrality scanning, cryptographic operations and resource limits.
- Replaced the affine Ed25519 hot path with iterative extended-coordinate
  arithmetic while preserving published vectors, receipt compatibility and
  strict malformed-input handling.
- Replaced per-object Git subprocesses with bounded batch streams and added a
  differential literal matcher without weakening deny-rule attribution or
  fail-closed resource limits.
- Streamed untracked worktree hashing, reduced Linux process-group sampling
  overhead and added lazy command-family imports for faster one-shot CLI use.
- Added synchronized English and Russian documentation for performance
  evidence, hard resource limits, advisory timings and operator-visible
  failure states.

## 1.77.0 - 2026-08-21

- Added a pinned development-only Ruff, mypy and coverage toolchain with a
  non-growing quality ratchet and a least-privilege CI workflow.
- Added stable redacted CLI errors for expected I/O, decoding, recursion and
  unexpected failures while preserving library and interruption behavior.
- Made built-in profiles available from installed wheels independently of the
  current directory, with explicit operator paths taking precedence.
- Added a measured 76% statement-line coverage floor, complete unittest
  discovery checks and an explicit documented Python API surface.
- Updated English and Russian quality, architecture, installation and CLI
  documentation and synchronized publication metadata to 1.77.0.

## 1.76.0 - 2026-08-21

- Turned module, package and layer boundaries into executable release gates with
  acyclic graph and complexity validation in CI.
- Split oversized process, launch, unified-start, metrics, parser, proof and
  thread-bridge paths behind compatible facades and shared bounded persistence
  primitives.
- Replaced central host-inspection branching with bounded, literal-only,
  adapter-owned `inspection_profile.py` files; unsupported profiles fail closed
  without executing adapter code.
- Consolidated only semantically identical validation, redaction, token and
  quality-mode primitives while preserving domain-specific contracts.
- Updated English and Russian architecture documentation and synchronized all
  package, plugin, installation and publication metadata to 1.76.0.

## 1.75.0 - 2026-08-21

- Hardened neutrality proof by binding signatures to claims, operation and the
  primary artifact identity.
- Prevented Git revision arguments from turning read-only reports into writes
  and rejected repository evidence paths that escape through symlinks.
- Added digest-bound local executable identity and expanded shared redaction for
  common standalone token formats.
- Made bounded JSON handling, private artifact permissions and Ed25519 decoding
  fail closed.
- Bound the complete authoritative plan package to its lock before audit or
  execution and verified full test discovery in CI.
- Hardened GitHub and PyPI publication controls while retaining the existing
  Trusted Publisher configuration.

## 1.74.0 - 2026-08-15

- Added three optional provider-neutral workflow presets for quick changes,
  research review and feature implementation.
- Added deterministic `project preset list`, `inspect`, `validate` and `render`
  commands with stable contracts and write-once local profile output.
- Added `start --preset` for one-off guided task intake without implicit host
  launch or model selection.
- Reused project-profile merge, frozen-plan authority, risk limits and Review
  Mesh mode identifiers instead of introducing a second workflow controller or
  quality policy.
- Added English and Russian documentation for preset selection, precedence,
  stage limits and advanced atomic control.

## 1.73.0 - 2026-08-15

- Added bounded, digest-bound project-principles artifacts that provide local
  defaults and constraints without replacing the frozen plan and lock.
- Added deterministic, read-only plan-delta reports for requirements, writes,
  acceptance, evidence, budgets, risks, gates and documentation changes.
- Added lineage checks that block package changes, non-increasing revisions,
  snapshot drift and lock drift before a delta is accepted.
- Added `project principles check`, `plan delta` and `plan delta-check` with
  offline release validators and public JSON contracts.
- Added English and Russian guidance for project governance and long-running
  plan continuity.

## 1.72.0 - 2026-08-15

- Added deterministic stratified sampling for the bundled reference-task suite,
  using bounded task family, lifecycle tier and task-shape dimensions.
- Added redacted benchmark execution records with lineage, execution setup,
  environment, scorer, quality, false-acceptance and measurement-gap fields.
- Added quality-first execution-setup validation and baseline/candidate
  comparison with explicit `NO_RECOMMENDATION` when the minimum evidence set is
  incomplete.
- Added `benchmark sample`, `benchmark receipt-check`, `benchmark qualify` and
  `benchmark compare-routes` commands without model calls, host launches or
  automatic policy adoption.
- Added English and Russian documentation for external harness evaluation,
  execution-setup validation and the related public contracts.

## 1.71.0 - 2026-08-14

- Added provider-neutral research evidence contracts for sources, claims,
  citations, provenance, validation and bounded summaries.
- Added local `research validate` and `research summary` commands with explicit
  source snapshots, duplicate and derivative-source checks, lifecycle
  boundaries and fail-closed content validation.
- Added English and Russian guidance for preparing research evidence before it
  is used as input to a reviewed plan.

## 1.70.0 - 2026-08-14

- Added privacy-preserving audit samples derived from existing review, usage and
  process receipts without storing prompts, host output, secrets or provider
  and model names.
- Added quality-first statistics for audit success, false acceptance,
  correction, disagreement, retry, timeout, token, wall-time and process
  resource signals.
- Added bounded holdout evaluation and advisory recommendations for packet
  size, reviewer count, timeout, retry limit and neutral route class. Changes
  require explicit approval and never mutate a frozen plan.
- Added local `metrics audit-sample`, `audit-report`, `audit-proposal` and
  `audit-apply` commands plus a release boundary validator.
- Added English and Russian documentation for evidence-based audit
  optimization and its quality-first approval flow.

## 1.69.0 - 2026-08-14

- Added redacted process-execution receipts with operation and attempt lineage,
  monotonic wall time, honest CPU/memory/process availability and bounded
  cleanup evidence.
- Added shell-free POSIX process-session and Windows job-object handling for
  timeout, cancellation and descendant cleanup.
- Added local execution-resource reports, bounded retry decisions and JSON
  host-harness integration without a background collector or model call.
- Added English and Russian guidance for diagnosing slow audits, unavailable
  measurements and cleanup blockers.

## 1.68.0 - 2026-08-14

- Added digest-bound Agent Plugins qualification profiles for Codex, Claude
  Code and Cursor.
- Added offline package qualification with seven-skill verification and an
  explicit read-only client probe with bounded process, time and output use.
- Added redacted qualification receipts that distinguish offline validation,
  local qualification, blocked checks and unavailable clients without claiming
  lifecycle or managed-launch proof.
- Added English and Russian documentation for client-owned installation and
  qualification boundaries.

## 1.67.0 - 2026-08-13

- Added a portable Agent Plugins 1.0.0 package containing the canonical ALK
  skills tree and a pinned local manifest schema.
- Added deterministic offline package build and validation with archive,
  containment, symlink and component-boundary checks.
- Added version-bound GitHub Release archive publication while preserving
  client-specific plugin and marketplace projections.
- Added English and Russian documentation for portable package loading and
  the distinction between skill availability and ALK lifecycle proof.

## 1.66.0 - 2026-08-13

- Added descriptor-driven thread-bridge capability profiles with explicit
  `UNSUPPORTED`, `WRAPPER_ONLY` and receipt-qualified `SUPPORTED` states.
- Added local `adapter thread-capability` and `adapter thread-qualify` checks;
  qualification validates adapter, host-range, policy and evidence lineage
  without making model or network calls in the core.
- Added conservative thread-bridge declarations to all bundled adapters,
  release validation, and contract tests that reject unsupported positive
  claims.
- Added English and Russian documentation for capability inspection,
  qualification receipts and adapter support boundaries.

## 1.65.0 - 2026-08-13

- Added an optional, provider-neutral thread bridge with typed capability,
  request, receipt, context-import and validation contracts.
- Added bounded `thread request` and `thread import` commands; native thread
  operations remain adapter-owned and mutating operations require approval and
  idempotency keys.
- Added project-profile `threadBridge` policy composition with frozen-plan
  limits, redacted non-authoritative context import and Review Mesh source
  projection.
- Added bilingual documentation and architecture call paths for thread
  context, continuity recovery and optional multi-model review.

## 1.64.0 - 2026-08-13

- Added typed context checkpoints with milestone, agent-requested,
  adapter-hook and unavailable capture modes.
- Added bounded local checkpoint storage, lineage-checked restoration and
  continuation receipts that never grant implementation authority.
- Added opt-in lifecycle checkpoint gates with atomic writes, idempotent
  retries and bounded retention.
- Added English and Russian operator documentation, CLI commands and contract
  validation for context continuity and recovery after compaction.

## 1.63.2 - 2026-08-12

- Added bilingual installation and first-run guides for GitHub checkouts and
  PyPI on macOS, Linux and Windows PowerShell.
- Added a task-oriented command map and simplified the quick start for terminal
  and host-plugin workflows.
- Expanded the architecture documentation with responsibility boundaries and
  the guarantee chain between ALK, the host, the model and the repository.
- Updated documentation compatibility and publication checks for the new
  onboarding pages and exact package pins.

## 1.63.1 - 2026-08-12

- Fixed the OpenCode adapter plugin export so the legacy OpenCode loader can
  load the plugin as a valid function.
- Kept the OpenCode projection side-effect-free and delegated lifecycle
  behavior to the shared Agent Lifecycle Kit core.

## 1.63.0 - 2026-08-12

- Added a read-only `audit package` command that checks an ALK plan directory,
  validates its frozen artifacts and can aggregate implementation audit reports
  for a reviewer handoff.
- Added typed package-audit report and validation contracts with bounded report
  discovery, ownership checks and strict completion gating.
- Added English and Russian documentation for reviewing a delivered plan and
  its implementation as a single package.

## 1.62.0 - 2026-08-12

- Added project-local workflow profiles for a unified `start` command with
  bounded stage defaults, explicit discovery controls and guided action
  receipts.
- Preserved frozen plan and lock authority through deterministic profile
  composition, path containment, no-model-call boundaries and bilingual
  operator documentation.

## 1.61.0 - 2026-08-10

- Added one provider-neutral execution strategy that composes existing risk,
  quality-floor, model-routing, compact-packet and review decisions without
  adding workflow or host-launch authority.
- Added quality-first comparison of reference-task evaluations, including
  attested token savings, invocation, retry, remediation and elapsed-time
  deltas; false acceptances and incomplete efficiency evidence remain blocked
  from automatic adoption.
- Added compact strategy summaries to unified start receipts and optional
  strategy projections for full and small-model task packet compilation.
- Added English and Russian operator guidance, architecture coverage, boundary
  validation and publication checks for Python 3.11-3.14.

## 1.60.0 - 2026-08-10

- Added a controller-produced task compatibility receipt so unchanged accepted
  tasks can retain their original implementation audit after a reviewed plan
  adoption without weakening exact lineage for other tasks.
- Added exact-version local planning profiles for Cursor, Gemini CLI, Qwen
  Code, Goose, Grok Build, Hermes, Kimi Code, OpenInterpreter and Pi, with one
  shared bounded qualification harness and thin adapter bindings.
- Classified Gemini CLI and Goose as static planning candidates and the other
  seven new profiles as explicitly unsupported. No adapter is promoted to
  `PLANNING_ONLY_QUALIFIED` without accepted live evidence.
- Added all-adapter profile validation, synchronized descriptor and capability
  facts, English and Russian support guidance, and publication metadata for
  Python 3.11-3.14.

## 1.59.0 - 2026-08-10

- Added explicit planning-only host launch for raw text or Markdown through
  `agent-lifecycle start --mode plan --launch`, while raw implementation remains
  blocked until independent review, freeze and a separate managed process.
- Added bounded stdin task transport, redacted output normalization,
  planning-session lineage, native containment evidence and unchanged-worktree
  postconditions without adding a second workflow or provider runtime.
- Added exact-version planning profile candidates for Codex, Claude Code and
  OpenCode. They remain `PLANNING_ONLY_UNSUPPORTED` until each host passes its
  own operator-approved live qualification.
- Added English and Russian operator guidance, contract and security tests, and
  publication checks for the planning-only bootstrap.

## 1.58.0 - 2026-08-10

- Added a versioned five-task reference suite with deterministic planning,
  architecture-review, Bug Forensics, S1 and S2 evidence oracles.
- Added read-only `benchmark evaluate` receipts for quality, false acceptance,
  retries, elapsed time and confidence-labeled token measurements.
- Added English and Russian operator guidance, architecture coverage, contract
  tests and publication checks for the reference evaluation workflow.

## 1.57.0 - 2026-08-10

- Added exact-version local launch profiles and bounded preflight evidence for
  Codex CLI 0.147.0, Claude Code 2.1.226 and OpenCode 1.18.15.
- Added digest-bound qualification receipts that block managed launch after a
  profile or host-version change while preserving every bundled descriptor at
  `WRAPPER_ONLY`.
- Added bounded host-local usage parsers with truthful `FIXTURE_ONLY` status,
  safe Codex and Claude inspection profiles, validators and English/Russian
  operator guidance.

## 1.56.0 - 2026-08-09

- Added ignored, schema-validated local host launch profiles with closed argv
  templates, exact environment allowlists, bounded timeouts and digest-bound
  inspection receipts.
- Added zero-process `host-launch inspect` and explicit one-probe `host-launch
  preflight` commands with redacted output.
- Added explicit `start --launch --host-launch-profile` execution only after a
  frozen lock-bound managed run and derived risk profile pass validation.
- Kept generic descriptor launch and `adapter session start --launch`
  fail-closed, preserved every bundled adapter at `WRAPPER_ONLY`, and added
  English and Russian operator and security guidance.

## 1.55.0 - 2026-08-09

- Added the Git-index-bound `tracked-release` neutrality scope for CI and
  release checks, including regular-file, symbolic-link and gitlink handling
  without submodule traversal.
- Added explicit policy-limited local artifact scanning with signed scope,
  revision, staged-entry, approved-root and content bindings.
- Added one bounded reread for identity races, keeping recovered races signed
  but informational while repeated races fail required-clean scans.
- Preserved legacy neutrality scopes with signed deprecation markers and added
  English and Russian operational guidance, validators and workflow tests.

## 1.54.0 - 2026-08-09

- Added bounded adapter-local usage normalizers for Gemini CLI, Kimi Code and
  Qwen Code, shared by each adapter runner and live harness through a contained
  descriptor-driven loader.
- Reused `agent-lifecycle-model-usage-receipt.v1` as a route- and
  source-bound sidecar while preserving the closed host-operation receipt.
- Distinguished host-attested, estimated, missing and invalid usage and kept
  fixture-only normalizers ineligible for S1/S2 usage gates.
- Added parser security validation, English and Russian operator guidance, and
  updated package, plugin, marketplace and exact installation metadata to
  `1.54.0`.

## 1.53.0 - 2026-08-09

- Added deterministic risk-aware execution profiles that derive a
  provider-neutral model route and token, invocation, and wall-time caps from a
  frozen S0/S1/S2 plan without model, network, or host calls.
- Added a read-only `start --risk --risk-profile-out` projection followed by
  explicit `workflow task-start --risk-profile` authorization with strict run,
  plan, task, source, operation, adapter, route, and digest lineage.
- Added fail-closed host usage checks for billable tokens, invocations, and wall
  time, while preserving advisory-only risk recommendations for raw task input.
- Added English and Russian operator guidance and updated package, plugin,
  marketplace, and quickstart publication metadata to `1.53.0`.

## 1.52.0 - 2026-08-09

- Added `agent-lifecycle start` as one beginner-facing command for task text,
  Markdown, explicit frozen-run delegation and stored ALK session resume.
- Added `auto`, `research`, `plan`, `review` and explicit `implement` modes with
  fail-closed execution boundaries and verified adapter/session lineage.
- Added `agent-lifecycle-start-receipt.v1`, path-safe delegate summaries,
  focused non-execution tests and English/Russian operator guidance.
- Updated package, plugin, marketplace and quickstart publication metadata to
  `1.52.0`.

## 1.51.0 - 2026-08-09

- Added Python 3.14 to package metadata and the tested CI, release, publication
  and neutrality workflow matrices while keeping Python 3.15 outside the
  supported range.
- Extended packaging smoke validation to build wheel and source distribution,
  install each in a separate clean environment and record both outcomes in one
  portable receipt.
- Documented the official versioned PyPI installation path and Python
  3.11-3.14 support in English and Russian.
- Updated package, plugin, marketplace and quickstart publication metadata to
  `1.51.0`.

## 1.50.2 - 2026-08-09

- Blocked generic descriptor-driven host launches and wildcard environment
  forwarding until a separately qualified local-launch path exists.
- Added shared receipt redaction, fail-closed neutrality completeness checks,
  descriptor installation metadata, and dependency-boundary validation.
- Split the CLI dispatcher into bounded routing modules without changing the
  public command contract.
- Updated package, plugin, marketplace, and quickstart publication metadata
  to `1.50.2`.

## 1.50.1 - 2026-08-07

- Added a PyPI Trusted Publisher workflow (`.github/workflows/publish.yml`)
  gated on a `pypi` environment approval, triggered by GitHub Release
  publication.
- Version-only bump so the release tag's commit includes the new publish
  workflow; no functional code changes.
- Updated package and plugin publication metadata to `1.50.1`.

## 1.50.0 - 2026-08-06

- Added deterministic Bug Forensics advisory policy for defect, regression,
  flaky failure, incident and security-bug task signals.
- Embedded advisory-only Bug Forensics recommendations in adapter task intake
  receipts without activating workflow gates.
- Added EN/RU Bug Forensics workflow guides and linked defect-repair examples
  from the lifecycle cookbook, task template and skill.
- Updated package and plugin publication metadata to `1.50.0`.

## 1.49.0 - 2026-08-06

- Added `agent-goal-progress-view.v1` and `agent-lifecycle goal view` to show
  current goal, lifecycle phase, next action, elapsed time, token usage and
  Git-style change counters from existing artifacts.
- Added terminal rendering for goal/progress views while keeping JSON output as
  the default machine-readable contract.
- Documented EN/RU goal progress examples in quickstarts, lifecycle cookbook,
  CLI reference and read-only status references.
- Updated package and plugin publication metadata to `1.49.0`.

## 1.48.0 - 2026-08-06

- Added `agent-external-context-import-receipt.v1` and validation for
  explicit local external context imports with source digests, citations and
  redaction status.
- Added `agent-lifecycle context external-import` and
  `context episode-retrieve` so imported context can appear as optional,
  non-proof episode retrieval hints.
- Documented EN/RU external memory safety boundaries, including no network,
  model, provider or hidden host calls from core.
- Updated package and plugin publication metadata to `1.48.0`.

## 1.47.0 - 2026-08-06

- Added EN/RU adapter event capture matrices covering native-hook status,
  wrapper routes, receipt routes, automatic-hook claims and adapter-owned
  boundaries.
- Added Codex, Claude Code and OpenCode event bridge guidance linked to
  existing neutral event stream conformance fixtures.
- Added `validate_adapter_event_guidance.py` to fail closed when declared
  event capture lacks documentation, receipt routes or truthful hook
  boundaries.
- Updated package and plugin publication metadata to `1.47.0`.

## 1.46.0 - 2026-08-06

- Added provider-neutral Review Mesh operator templates for leader draft
  review, parallel research synthesis and implementation-audit panels.
- Added `agent-lifecycle review-mesh template-list` and `review-mesh prepare`
  to build local profiles, assignment packets and prepare receipts without
  launching reviewer hosts or providers.
- Documented replaceable Codex, Claude Code and OpenCode/GLM examples while
  keeping portable contracts on neutral model classes.
- Updated package and plugin publication metadata to `1.46.0`.

## 1.45.0 - 2026-08-06

- Added EN/RU lifecycle cookbook recipes for research-only work, Markdown plan
  review, code review, implementation audit and optional cross-review.
- Added draft-only task templates for research plans, Markdown plan review,
  implementation audit and cross-review.
- Linked cookbook guidance from quickstarts, CLI references and workflow/audit
  skills so beginners can start with recipes while advanced users can use
  atomic commands.
- Updated package and plugin publication metadata to `1.45.0`.

## 1.44.0 - 2026-08-06

- Added draft-only OpenSpec, GitHub Spec Kit, BMAD and Spec Kitty planning
  import profiles on top of the existing ALK planning import path.
- Added deterministic Markdown file and folder import provenance with stable
  source digests, bounded input size and redacted file labels.
- Extended `agent-lifecycle import plan` with `--dialect` and folder support,
  plus EN/RU docs and CLI examples for external planning imports.
- Updated package and plugin publication metadata to `1.44.0`.

## 1.43.0 - 2026-08-06

- Added a Review Mesh workflow cookbook with common planning, research, bug
  investigation, implementation-audit and release/security review scenarios in
  EN/RU docs.
- Added `review-mesh profile` for command-only profile creation and refreshed
  RU terminology/examples for grouped review workflows.
- Added `agent-publication-adoption-validation.v1` and a local adoption
  validator for quickstart, support-matrix and project-comparison documentation.
- Surfaced `managedLaunch.status: WRAPPER_ONLY` in the public adapter support
  matrix without changing adapter maturity claims.
- Added EN/RU project-comparison pages explaining ALK as a lifecycle
  controller rather than a runtime, model broker or memory system.
- Updated package and plugin publication metadata to `1.43.0`.

## 1.42.0 - 2026-08-05

- Added semi-automatic Review Mesh assignment packets, reviewer result import,
  synthesis and quorum receipts for opted-in planning, research and
  implementation-audit phases.
- Added workflow, implementation-audit and finalization quorum gates that fail
  closed only when the frozen plan explicitly requires Review Mesh evidence.
- Documented Review Mesh assignment/quorum usage in EN/RU docs and refreshed
  publication metadata to `1.42.0`.

## 1.41.0 - 2026-08-05

- Added `agent-review-mesh-recommendation.v1` and a deterministic
  `review-mesh recommend` advisor for task text, task files, adapter task
  intake receipts and plan manifests.
- Integrated advisory Review Mesh recommendations into adapter task intake
  without changing draft-only raw-input execution boundaries.
- Documented Review Mesh recommendations in EN/RU docs and refreshed
  publication metadata to `1.41.0`.

## 1.40.0 - 2026-08-05

- Added optional Review Mesh public schemas for multi-reviewer planning,
  research synthesis and implementation-audit panel workflows.
- Added provider-neutral Review Mesh validators that reuse cross-check budget
  and independence semantics without launching adapters or model providers.
- Documented Review Mesh boundaries in EN/RU docs and refreshed publication
  metadata to `1.40.0`.

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
