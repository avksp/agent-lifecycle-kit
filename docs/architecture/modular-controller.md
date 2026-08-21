# Modular controller architecture

This document defines the production shape of the Agent Lifecycle Kit
controller. It is intentionally host-neutral and applies to every adapter under
`adapters/*`, including Codex, Claude Code, Cursor, Gemini CLI, Goose, Grok
Build, Hermes, Kimi Code, OpenCode, OpenInterpreter, Pi and Qwen Code.

## Status

The historical monolithic `workflowctl.py` controller is not part of the
standalone production source. It remains a characterization and bootstrap
reference only in source projects that still carry it.

The standalone release implements the controller as a modular Python package
with thin entry points and domain packages behind them. The target boundary map
below is no longer only a future shape: most major seams now have production
modules. Reserved seams should still become packages only when behavior exists
or when splitting prevents a file/context limit breach.

## Current implementation map

This is the current source map for the standalone package:

| Responsibility | Current module(s) | Status |
| --- | --- | --- |
| Stable contracts, canonical JSON, digests, schemas, typed errors | `contracts/*` | Implemented |
| Git diff discovery for ownership audit | `changesets/git.py` | Implemented |
| Ownership, implementation, package, proof-integrity and review-verdict audit | `audit/*` | Implemented |
| SDD tier and plan manifest validation | `planning/*`, `specification/*`, `review/*` | Implemented validators |
| Plan lock verification | `freeze/locks.py` | Implemented |
| Frozen DAG to task-packet and small-model packet compilation | `compiler/task_packets.py`, `compiler/small_model_packets.py` | Implemented |
| Compact context profiles, rendering, episode retrieval and external context | `context/*`, `context/external_memory.py`, `evidence_index/external_context.py` | Implemented |
| Durable workflow state, operation kernel, event log, task/run transitions, gate checks, finalization | `workflow/*` | Implemented |
| Neutrality authority, scanning, signed receipts, controller-gate helper | `neutrality/*` | Implemented |
| Host capability descriptors, inspection, event capture and validation | `host_protocol/*`, adapter metadata files | Implemented as offline descriptors and validation contracts |
| Adapter task intake, sessions, launch profiles and workflow bridge | `adapter_sessions/*` | Implemented |
| External workflow, dialect and planning imports | `imports/*`, including OpenSpec, Spec Kit, BMAD and Spec Kitty profiles | Implemented as draft-only import mappers |
| Readiness diagnostics and diagnostic bundles | `diagnostics/*` | Implemented |
| Evidence indexes, episode indexes and external-context receipts | `evidence_index/core.py`, `evidence_index/episode_index.py`, `evidence_index/external_context.py` | Implemented |
| Goal records, objective snapshots, read-only goal view and follow-up records | `goal/records.py`, `goal/view.py`, `followup/*` | Implemented |
| Usage, phase resources, cost accounting and outcome signals | `metrics/*` | Implemented |
| Model class routing and provider-neutral receipts | `model_routing/*` | Implemented |
| Adaptive lifecycle policy, quality-floor decisions and provider-neutral execution strategy | `policy/*`, including `policy/execution_strategy.py`, plus `cli/strategy.py` | Implemented |
| Deterministic reference-task evaluation and quality-first strategy comparison | `benchmarks/*`, `contracts/benchmark_schemas.py`, `cli/benchmarks.py` | Implemented |
| Optional quality profiles, cross-check, bug forensics and Bug Forensics advisory | `quality/*`, `quality/bug_forensics_advisor.py` | Implemented |
| Read-only status, progress, event feed and change summaries | `reporting/*` | Implemented |
| Optional multi-review coordination, operator templates, prepared packets, assignments, result import, synthesis and quorum | `review_mesh/*`, `review_mesh/operator_templates.py` | Implemented |
| Controlled runner, attempt snapshots and sandbox receipts | `runner/*` | Implemented |
| Worktree isolation receipts | `worktree/*` | Implemented |
| Root CLI dispatch | `cli/main.py`, `cli/parsers.py`, `cli/dispatch.py`, `cli/dispatch_adapters.py`, `cli/dispatch_contracts.py`, `cli/dispatch_lifecycle.py`, `cli/dispatch_observability.py`, `cli/dispatch_planning.py` | Implemented thin entrypoint and command-group handlers; no lifecycle semantics should move here |
| Release checks and live adapter promotion evidence | `tools/release/*`, `tools/live_hosts/*`, metadata and docs | Implemented as release validators and host-local evidence tooling |

Current size check: `cli/main.py` and `cli/dispatch.py` are thin entrypoints at
41 and 53 lines respectively. The root dispatcher selects a focused adapter/readiness,
contract/evidence, lifecycle, observability or planning handler; policy,
follow-up and worktree handlers remain dedicated command modules. Most
production Python files are below the hard limits in this document.
`workflow/plan_adoption.py`, `workflow/finalization.py` and
`workflow/task_transitions.py` remain about 420-440 lines. New lifecycle
behavior should prefer a focused domain module and a small dispatcher submodule
instead of expanding `cli/dispatch.py`.

## Target shape

The long-term production controller is organized around these boundaries. A
boundary should become a package only when runtime behavior exists for it or
when splitting prevents a file/context limit breach:

- `contracts`: public schemas, canonical JSON, digests, and typed errors.
- `ports`: host, filesystem, Git, signing, clock, process, and telemetry ports;
  currently lightweight and mostly represented by direct stdlib calls.
- `state`: state/WAL schemas, readers, projections, and compatibility; currently
  implemented under `workflow/state.py` and `workflow/events.py`.
- `operation_kernel`: atomic state/event/WAL transactions and crash recovery;
  currently implemented as `workflow/operation_kernel.py` for expected
  revision checks, operation-id idempotency, state revision mutation, operation
  ledger, event append, and atomic state replacement.
- `planning`: SDD tier resolution, specification, review, and freeze logic.
- `context`: compact profile validation, active-packet rendering, overflow
  checks, and context receipts for small-context hosts.
- `compilation`: frozen DAG to task packet compilation and verification;
  currently `compiler/task_packets.py`.
- `authorization`: approval receipts, bootstrap preflight, and auto-authorize;
  currently limited to run authorization fields in `workflow/plan_adoption.py`.
- `task_runtime`: launch, status, attempt, remediation, and acceptance flow;
  currently `workflow/task_transitions.py` plus selectors.
- `runner`: bounded execution loop over existing workflow primitives; the
  transition-state contract and extension points are documented in
  `runner-transition-contract.md` and `runner-extension-map.md`.
- `validation`: controller gates, command receipts, release validators and
  validation indexes; currently `workflow/gates.py`, `neutrality/gate.py` and
  `tools/release/*`.
- `audit`: ownership, task and package implementation audits, proof integrity,
  review verdicts and final audit validators; currently `audit/*`,
  `workflow/reviews.py` and `workflow/finalization.py`.
- `quality`: bug-forensics, cross-check, failure classification and optional
  quality packs.
- `review_mesh`: optional multi-review recommendation, assignments, imported
  results, synthesis and quorum validation.
- `adapter_sessions`: descriptor-driven task intake, session records, secure
  launch profiles and the managed workflow bridge.
- `reporting`: read-only status, event feed, lifecycle progress, progress
  hooks and change summaries.
- `metrics`: token/resource accounting, usage export, outcome indexes and
  quality-cost recommendations.
- `model_routing`: provider-neutral model class decisions and receipts.
- `execution_strategy`: provider-neutral composition of risk, quality floor,
  model class, packet size, review depth and resource limits; currently
  `policy/execution_strategy.py` with CLI and compiler projections.
- `benchmarks`: deterministic reference-task evaluation and quality-first
  comparison receipts; currently `benchmarks/*` and `cli/benchmarks.py`.
- `worktree`: worktree isolation policies and attempt receipts.
- `release`: release candidate, release inventory, and support matrix; currently
  docs, metadata and release validators.
- `terminal`: terminal progress rendering only; direct terminal host operations
  remain outside core.
- `finalization`: final proof, terminal proof, and COMPLETE replay checks;
  currently final proof and final audit validation in `workflow/finalization.py`.
- `adapters`: host-specific projections only, with no lifecycle semantics.
- `api`: stable public API over the modular services; currently the package
  facades and root CLI.
- `cli`: argument parsing and compact rendering only.

The dependency direction is one-way: lower layers cannot import CLI, API, or
surface adapters; adapters cannot import controller domain services directly.
Controller services depend on ports and contracts rather than native host APIs.

## Enforced architecture boundaries

The reviewed package levels are recorded in
`policy/architecture-dependencies.json`. The release validator builds the
module graph from the source tree, includes imports inside functions, rejects
non-trivial module and package cycles, and checks that every edge follows the
declared layer direction. CI runs this check together with the source-size and
function-complexity validator, so the architecture is an executable release
condition rather than a diagram-only convention. The current graph is
acyclic; a new dependency must update the policy and pass independent review.

Runtime boundaries follow the same rule. `adapter_sessions/process.py` is the
bounded process boundary; `process_capture.py` owns stream capture and
`process_control.py` owns timeout, cleanup and receipt assembly. The public
launcher and start modules retain compatible facades while the implementation
is split behind them. Persistence helpers in `contracts/persistence.py` keep
private create, replace and permission rules in one implementation.

Host inspection is open for adapter-owned data, not for arbitrary code.
Each adapter may provide a literal-only `inspection_profile.py`. ALK validates
the profile, resolves only an allow-listed inspection handler and reports an
unsupported profile without starting a host process. Loading the profile uses
bounded literal parsing and never imports adapter code. Adding an adapter
inspection profile therefore does not require a new host-name branch in the
lifecycle core.

## Size and context limits

The standalone implementation must be usable by small-context models. File and
function limits are therefore release gates, not style preferences.

- Production Python source file target: 800 lines or less.
- Production Python source file hard limit: 1200 lines.
- Function or method target: 80 lines or less.
- Function or method hard limit: 150 lines.
- Root CLI entrypoint target: 80 lines or less.
- Root CLI entrypoint hard limit: 150 lines.
- Parser and dispatcher modules should stay below the production hard limit;
  files above the 800-line source target are explicit split candidates.
- External launcher target: 12 lines or less.
- External launcher hard limit: 24 lines.
- Top-level symbols target per module: 40 or fewer.
- Top-level symbols hard limit per module: 80.

The exact context authority is the rendered C8 subject, not a line-count
heuristic. Every changed production slice must have a bounded subject that fits
the C8 profile, and overflow must be resolved by splitting the subject or
module before review.

The `small-context-profile.v1` release profile is the portable compact-context
baseline. It supports 4k-strict, 8k, 16k, 32k, and 64k hosts and forbids silent
truncation. The CLI also exits non-zero when a rendered context receipt fails
its budget checks. A host may use a larger local context, but the adapter cannot
claim compact-mode support unless the core-rendered envelope and receipt pass
unchanged.

The receipt must enforce every bundled profile budget at runtime: rendered
envelope, reserved-output budget, active packet, state summary, accepted
evidence summary, optional `toolOutputs`, and recent verbatim user-turn count.
If any check fails, the controller blocks or splits instead of producing a
truncated prompt.

Controller gates are runtime preconditions, not advisory metadata. Task and
finalization transitions validate every gate configured for the current phase by
resolving the frozen receipt path and checking receipt binding, freshness,
dependencies, PASS verdict, and required attestation fields before mutating
state.

## SOLID

SOLID is required where it creates testable boundaries:

- Single responsibility: each module owns one lifecycle concern.
- Open/closed: new host adapters are added through ports and adapter packages,
  not by editing lifecycle core branches.
- Liskov/interface segregation: adapters implement explicit capability
  contracts and fail closed for unsupported operations.
- Dependency inversion: lifecycle logic depends on ports, not concrete host
  runtimes or shell wrappers.

SOLID is not a reason to create deep inheritance, abstract factories, or
framework-heavy structure. Prefer small pure functions, dataclasses, protocols,
and explicit composition.

## DRY

DRY is mandatory for lifecycle semantics and security-sensitive logic:

- one canonical JSON implementation;
- one digest/signature path per domain;
- one operation kernel for state/WAL commits;
- one evidence and receipt validation path;
- one adapter capability model.

DRY must not collapse different trust domains into one generic helper. Similar
code may stay separate when bootstrap, release, terminal, task, and validation
domains need different signatures, schemas, or failure semantics.

## YAGNI

YAGNI is required for adapter and plugin scope:

- ship only the five canonical lifecycle skills;
- keep optional live adapter promotion outside the release prerequisite;
- do not add MCP servers, apps, hooks, or marketplaces unless the target host
  actually requires them;
- do not implement provider-specific model routing in the core;
- do not ship project profiles or source-project samples in this repository.

YAGNI does not remove required safety. The controller still needs durable
state, WAL, immutable locks, independent review, evidence binding, authority
checks, bounded context, crash recovery, and final proof because those are core
product requirements.

## Acceptance gate

A release candidate fails if any of these are true:

- the production source imports, executes, or reintroduces a historical
  monolithic `workflowctl.py`;
- lifecycle semantics are implemented separately in host adapters;
- a module exceeds the hard size/context limits without an approved split;
- security-sensitive canonicalization, signing, receipt, or WAL logic has more
  than one authoritative implementation path;
- any adapter support is claimed above the conformance evidence actually present
  in the support matrix;
- samples, fixtures, or evaluations contain source-project names, paths,
  credentials, or artifacts.
