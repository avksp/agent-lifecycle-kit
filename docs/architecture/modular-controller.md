# Modular Controller Architecture

This document defines the production shape of the Agent Lifecycle Kit
controller. It is intentionally host-neutral and applies to Codex, Claude Code,
Cursor, Hermes, OpenCode, and future adapters.

## Status

The historical monolithic `workflowctl.py` controller is not part of the
standalone production source. It remains a characterization and bootstrap
reference only in source projects that still carry it.

The standalone release implements the controller as a modular Python package
with thin CLI entry points. The current structure is intentionally smaller than
the full target boundary map below: missing packages are reserved seams, not a
release requirement unless their responsibility becomes implemented runtime
logic.

## Current Implementation Map

This is the current source map for the standalone package:

| Responsibility | Current module(s) | Status |
| --- | --- | --- |
| Stable contracts, canonical JSON, digests, schemas, typed errors | `contracts/*` | Implemented |
| Git diff discovery for ownership audit | `changesets/git.py` | Implemented |
| Ownership audit over frozen plan write sets | `audit/ownership.py` | Implemented |
| SDD tier and plan manifest validation | `planning/*`, `specification/*`, `review/*` | Implemented validators |
| Plan lock verification | `freeze/locks.py` | Implemented |
| Frozen DAG to task-packet compilation | `compiler/task_packets.py` | Implemented |
| Compact context profiles and receipts | `context/*` | Implemented |
| Durable workflow state, event log, task/run transitions, gate checks, finalization | `workflow/*` | Implemented |
| Neutrality authority, scanning, signed receipts, controller-gate helper | `neutrality/*` | Implemented |
| Host capability descriptors | `host_protocol/contracts.py`, adapter metadata files | Implemented as offline descriptors |
| Root CLI dispatch | `cli/main.py` | Implemented thin dispatcher; no lifecycle semantics should move here |
| Release, terminal, live adapter promotion | Metadata/docs only | Reserved until verified host evidence exists |

Current size check: all production Python files are below the hard limits in
this document. The largest files are `cli/main.py` at roughly 405 lines and
`workflow/plan_adoption.py` at roughly 400 lines; both are within the current
hard limits but remain split candidates if more behavior is added.

## Target Shape

The long-term production controller is organized around these boundaries. A
boundary should become a package only when runtime behavior exists for it or
when splitting prevents a file/context limit breach:

- `contracts`: public schemas, canonical JSON, digests, and typed errors.
- `ports`: host, filesystem, Git, signing, clock, process, and telemetry ports;
  currently lightweight and mostly represented by direct stdlib calls.
- `state`: state/WAL schemas, readers, projections, and compatibility; currently
  implemented under `workflow/state.py` and `workflow/events.py`.
- `operation_kernel`: atomic state/event/WAL transactions and crash recovery;
  currently local to workflow transition modules and the next split candidate.
- `planning`: SDD tier resolution, specification, review, and freeze logic.
- `context`: compact profile validation, active-packet rendering, overflow
  checks, and context receipts for small-context hosts.
- `compilation`: frozen DAG to task packet compilation and verification;
  currently `compiler/task_packets.py`.
- `authorization`: approval receipts, bootstrap preflight, and auto-authorize;
  currently limited to run authorization fields in `workflow/plan_adoption.py`.
- `task_runtime`: launch, status, attempt, remediation, and acceptance flow;
  currently `workflow/task_transitions.py` plus selectors.
- `validation`: controller gates, command receipts, and validation indexes;
  currently `workflow/gates.py` and `neutrality/gate.py`.
- `audit`: ownership, task review, final audit validators; currently
  `audit/ownership.py`, `workflow/reviews.py`, and `workflow/finalization.py`.
- `release`: release candidate, release inventory, and support matrix; currently
  docs and metadata only.
- `terminal`: terminal host operations and independent terminal review; reserved.
- `finalization`: final proof, terminal proof, and COMPLETE replay checks;
  currently final proof and final audit validation in `workflow/finalization.py`.
- `adapters`: host-specific projections only, with no lifecycle semantics.
- `api`: stable public API over the modular services; currently the package
  facades and root CLI.
- `cli`: argument parsing and compact rendering only.

The dependency direction is one-way: lower layers cannot import CLI, API, or
surface adapters; adapters cannot import controller domain services directly.
Controller services depend on ports and contracts rather than native host APIs.

## Size And Context Limits

The standalone implementation must be usable by small-context models. File and
function limits are therefore release gates, not style preferences.

- Production Python source file target: 800 lines or less.
- Production Python source file hard limit: 1200 lines.
- Function or method target: 80 lines or less.
- Function or method hard limit: 150 lines.
- CLI dispatcher target: 300 lines or less.
- CLI dispatcher hard limit: 500 lines.
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

## Acceptance Gate

A release candidate fails if any of these are true:

- the production source imports, executes, or reintroduces a historical
  monolithic `workflowctl.py`;
- lifecycle semantics are implemented separately in host adapters;
- a module exceeds the hard size/context limits without an approved split;
- security-sensitive canonicalization, signing, receipt, or WAL logic has more
  than one authoritative implementation path;
- Codex, Claude Code, Cursor, Hermes, or OpenCode support is claimed above the
  conformance evidence actually present in the support matrix;
- samples, fixtures, or evaluations contain source-project names, paths,
  credentials, or artifacts.
