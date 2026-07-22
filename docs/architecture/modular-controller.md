# Modular Controller Architecture

This document defines the production shape of the Agent Lifecycle Kit
controller. It is intentionally host-neutral and applies to Codex, Claude Code,
Cursor, Hermes, OpenCode, and future adapters.

## Status

The large historical `workflowctl.py` controller is a transitional
characterization and bootstrap reference only. It must not be copied into the
standalone release as the production implementation.

The standalone release must implement the controller as a modular Python
package with a thin CLI entry point. The CLI may preserve stable commands, JSON
output, exit codes, state/WAL semantics, and compatibility fixtures, but the
implementation behind those commands must be split by responsibility.

## Required Shape

The production controller is organized around these boundaries:

- `contracts`: public schemas, canonical JSON, digests, and typed errors.
- `ports`: host, filesystem, Git, signing, clock, process, and telemetry ports.
- `state`: state/WAL schemas, readers, projections, and compatibility.
- `operation_kernel`: atomic state/event/WAL transactions and crash recovery.
- `planning`: SDD tier resolution, specification, review, and freeze logic.
- `context`: compact profile validation, active-packet rendering, overflow
  checks, and context receipts for small-context hosts.
- `compilation`: frozen DAG to task packet compilation and verification.
- `authorization`: approval receipts, bootstrap preflight, and auto-authorize.
- `task_runtime`: launch, status, attempt, remediation, and acceptance flow.
- `validation`: controller gates, command receipts, and validation indexes.
- `audit`: task and final audit validators.
- `release`: release candidate, release inventory, and support matrix.
- `terminal`: terminal host operations and independent terminal review.
- `finalization`: final proof, terminal proof, and COMPLETE replay checks.
- `adapters`: host-specific projections only, with no lifecycle semantics.
- `api`: stable public API over the modular services.
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

- the production CLI imports or executes the historical monolithic
  `workflowctl.py`;
- lifecycle semantics are implemented separately in host adapters;
- a module exceeds the hard size/context limits without an approved split;
- security-sensitive canonicalization, signing, receipt, or WAL logic has more
  than one authoritative implementation path;
- Codex, Claude Code, Cursor, Hermes, or OpenCode support is claimed above the
  conformance evidence actually present in the support matrix;
- samples, fixtures, or evaluations contain source-project names, paths,
  credentials, or artifacts.
