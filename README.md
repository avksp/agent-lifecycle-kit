<p align="center">
  <img src="docs/assets/agent-lifecycle-kit-banner.svg?v=2026-08-02-1" alt="Agent Lifecycle Kit - plan, execute, prove, finish agent work" width="100%">
</p>

# Agent Lifecycle Kit

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/avksp/agent-lifecycle-kit?label=release)](https://github.com/avksp/agent-lifecycle-kit/releases)
![Python](https://img.shields.io/badge/python-3.11--3.14-blue.svg)

**Agent Lifecycle Kit (ALK)** coordinates coding-agent work through a verifiable
finish. It keeps the requested outcome, reviewed plan, execution boundaries,
evidence and acceptance decisions connected while the external agent changes the
project.

The provider-neutral workflow works with Codex, Claude Code, Qwen Code, Goose,
OpenInterpreter, Pi, Grok Build, or another CLI. Provider commands, model choice,
and secret handling stay in adapters or host-local profiles.

## Quick start
From a source checkout:

```bash
python -m pip install -e .
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
agent-lifecycle start --adapter <adapter-id> --text "Draft a reviewed implementation plan"
```

Choose `<adapter-id>` from the [adapter support matrix](docs/adapters/support-matrix.md).

The official [PyPI package](https://pypi.org/project/agent-lifecycle-kit/) supports Python 3.11-3.14.
Install the exact release with `python -m pip install agent-lifecycle-kit==1.61.0`.

Use [Quickstart](docs/guides/quickstart.md), [task workflows](docs/guides/how-alk-works.md),
and the [Lifecycle cookbook](docs/guides/lifecycle-cookbook.md). The [planning-only](docs/reference/planning-only-launch.md)
and [qualified frozen-task](docs/reference/qualified-host-launch.md) guides define launch boundaries.
See [System architecture](docs/architecture/system-architecture.md), [Project comparison](docs/reference/project-comparison.md),
and [Документация на русском](docs/ru/README.md).

## What it gives you
- A finish-oriented lifecycle: plan, execute, review, and prove the result.
- One process for different CLIs: adapter-specific commands stay outside the
  core, and new adapters can be added without changing lifecycle schemas.
- Small-model friendly packets: compact context, clear next actions, and
  deterministic checks for local or cheaper models.
- Quality without overengineering: one provider-neutral execution strategy
  composes risk, model class, packet size, review and resource limits.
- Usage visibility: tokens, time, and resource counters are native; monetary
  cost is optional and only used when a metered host reports it.
- Read-only progress and managed sessions: host UIs can show lifecycle state,
  attested tokens and Git-style change counters; `start` accepts task text,
  Markdown, frozen run requests or stored ALK sessions while preserving
  review/freeze boundaries.

## Feature areas
### Plan and execute

- Reviewed specification and plan flow before implementation starts.
- Deterministic task packets for splitting work across agents.
- Execution records capture completion checks, blockers, retries, and final
  proof; missing required evidence fails the step.
- Ready-made task templates cover bug fixes, idea-to-PR flow, PR review,
  merge-conflict repair, and release-readiness work.

### Quality and proof

- Implementation audits compare results with the frozen plan and acceptance
  evidence.
- For explicit bug and regression repair, the optional Bug Forensics profile
  records reproduction, fingerprint, failure class, hypotheses, minimal patch,
  regression proof, and reusable recipes.
- Optional proof-integrity evidence for high-risk final proofs: stable findings,
  root-cause digests, fix-impact receipts, and hash chains.
- Cross-checks and runtime-policy receipts are opt-in controls; plans can
  require proof for an external system update before acceptance.
- Optional multi-model review can use any available adapter/model bindings;
  Codex, Claude Code and OpenCode/GLM are examples, not a required roster.
  Review Mesh prepares packets, imports answers, synthesizes findings and checks
  quorum, while the operator or host wrapper starts each model. The bundled reference-task suite measures deterministic quality, false acceptances, retries, elapsed time, and confidence-labeled token usage.

### Routing and resource control

- Compact context profiles, small-model packets, objective snapshots, and
  local quality-cost learning help choose the lightest safe mode.
- Phase resource measurements reuse the usage export envelope for tokens,
  duration, and resource counters without mandatory monetary accounting.
- Usage/session exports include tokens, resources, receipt digests, and optional
  host-reported `cost_usd`.

### Security and containment

- Release neutrality scans bind the Git index and current revision; ignored local evidence is read through an explicit policy-limited flag. Host-supplied rules keep local paths, secrets, trust roots and signing keys out of portable artifacts.
- Host environment access uses explicit `--host-env-allow`; receipts store redacted metadata, and qualified local profiles provide the managed launch route.
- Imports, diagnostics, and usage exports redact local paths and common secret markers before validation.
- Sandbox receipts separate runtime filesystem, network, process, and environment containment from git write-scope.
- Release security gates validate portable paths, credentials, adapter scope and production claims.

### Adapters and interop

- Adapter contracts keep host-specific projections separate from lifecycle
  schemas.
- New CLI hosts start as adapters: descriptor, command projection, environment
  boundary, and verification evidence live outside the lifecycle core.
- Adapter capability checks and progress bridge support compare live receipts
  and display lifecycle state while support levels remain evidence-driven.
- Import mappers and issue-to-spec intake normalize external workflows, agent
  dialects, and tickets into reviewable draft context.
- Lightweight episode retrieval over receipt/session summaries keeps digest
  provenance and explicit `chainVerified` or `chainUnchecked` state.

### Operations

- Runner recovery receipts cover attempt snapshot, restore, abandon, selected
  attempt, worker lease, and heartbeat state.
- Read-only diagnostics, event feeds, managed lifecycle steps, progress watch
  receipts, and change summaries inspect checkout and workflow state without
  model calls.

## Daily flow

Spec -> frozen plan -> bounded work -> implementation audit -> final proof.
Core commands cover specification, plan, workflow, audit, adapters, imports, metrics,
policy, diagnostics, runner state, and adapter task intake. See [CLI reference](docs/reference/cli.md) and [Source of truth](docs/reference/source-of-truth.md).

## Adapter support level

The adapter support level describes how much of the ALK integration is verified
for a specific host. It covers the declared CLI/version, command projection,
environment boundary, live conformance, resource calibration and accepted ALK
lifecycle evidence. It describes the checked integration range; it is not a
rating of the host model or of the external product.

Accepted lifecycle artifacts include the reviewed plan and lock, state and task
receipts, validation and evidence summaries, independent plan and implementation
audits, and final proof. Host launch routes add usage, resource and containment
receipts for the exact adapter/version binding.

`EXPERIMENTAL` marks an adapter with offline checks and deterministic contract
tests. `VERIFIED` adds bounded live host conformance, usage/resource calibration,
accepted redacted evidence and lifecycle final proof for a defined host range.
Each adapter page and the support matrix name the exact CLI, version and
host-local binding covered by the evidence.
The matrix covers Codex, Claude Code, Cursor, Gemini CLI, Goose, Grok Build,
Hermes, Kimi Code, OpenCode, OpenInterpreter, Pi and Qwen Code.

Adapter installation and support-level details live in [Adapter install](docs/adapters/install.md) and [Adapter support matrix](docs/adapters/support-matrix.md).

## Contract map

The public lifecycle surface is schema-backed. Full stable schema ids, compatibility rules, runner recovery, cross-check, Review Mesh, Bug Forensics and usage export details are listed in [Public contracts](docs/reference/public-contracts.md).

## Design boundaries

- The core stays provider-neutral. Concrete host commands and model bindings
  live in adapters or host-local profiles.
- New CLIs are integrated through adapters: descriptor, command projection,
  environment boundary, and verification evidence. The lifecycle schemas remain
  stable while host support grows.
- Small models get compact packets, deterministic checks, and explicit
  next-action lists instead of long narrative state.
- All model sizes follow the same evidence gates; larger models receive the same
  bounded workflow with richer reasoning capacity.
- Public release claims use tracked source files and redacted evidence summaries.
- External dialect imports and retrieved episodes enrich context, while reviewed
  ALK artifacts remain the source of truth.
- Cross-check, Review Mesh and runner recovery receipts add evidence when a task
  or plan enables them; the operator chooses the review depth.

## Documentation

- Start: [English documentation](docs/README.md), [Русская документация](docs/ru/README.md), [Quickstart](docs/guides/quickstart.md), [Lifecycle cookbook](docs/guides/lifecycle-cookbook.md), and [Code review workflows](docs/guides/code-review-workflows.md).
- Planning and adapters: [Issue to specification drafts](docs/guides/issue-to-spec.md), [Adapter install](docs/adapters/install.md), and [Adapter support matrix](docs/adapters/support-matrix.md).
- Reference: [System architecture](docs/architecture/system-architecture.md), [execution strategy](docs/reference/execution-strategy.md), [CLI reference](docs/reference/cli.md), [Source of truth](docs/reference/source-of-truth.md), [Managed lifecycle runner](docs/reference/managed-lifecycle-runner.md), [Managed adapter sessions](docs/reference/managed-adapter-sessions.md), [Implementation audit](docs/reference/implementation-audit.md), [Plan completeness](docs/reference/plan-completeness.md), [Public contracts](docs/reference/public-contracts.md), and [Readiness diagnostics](docs/reference/readiness-diagnostics.md).
- Quality and resources: [Reference-task evaluation](docs/reference/reference-task-evaluation.md), [model routing](docs/reference/model-routing.md), [quality-cost learning](docs/reference/quality-cost-learning.md), [lifecycle cost accounting](docs/reference/lifecycle-cost.md), [host-local token accounting](docs/reference/host-local-token-accounting.md), [Usage export](docs/reference/usage-export.md), and [Evidence integrity](docs/reference/evidence-integrity.md).
- Profiles and operations: [Read-only status views](docs/reference/read-only-status-view.md), [Adapter progress bridge](docs/reference/automatic-progress-bridge.md), [Sandbox boundaries](docs/reference/sandbox-boundaries.md), [Import mappers](docs/reference/import-mappers.md), [Episode retrieval](docs/reference/episode-retrieval.md), [Runner recovery](docs/reference/runner-recovery.md), [Cross-check profile](docs/reference/cross-check-profile.md), [Review Mesh](docs/reference/review-mesh.md), [Bug Forensics profile](docs/reference/bug-forensics.md), and [Bug Forensics context budget](docs/reference/bug-forensics-context-budget.md).
- Release assets: [Task templates](templates/tasks/README.md), [Neutrality scanning](docs/reference/neutrality.md), and [Release security](docs/security/release-security.md).

Apache-2.0. See [LICENSE](LICENSE).
