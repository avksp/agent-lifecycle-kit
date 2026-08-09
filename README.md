<p align="center">
  <img src="docs/assets/agent-lifecycle-kit-banner.svg?v=2026-08-02-1" alt="Agent Lifecycle Kit - plan, execute, prove, finish agent work" width="100%">
</p>

# Agent Lifecycle Kit

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/avksp/agent-lifecycle-kit?label=release)](https://github.com/avksp/agent-lifecycle-kit/releases)
![Python](https://img.shields.io/badge/python-3.11--3.14-blue.svg)

**Agent Lifecycle Kit (ALK)** gives coding agents one delivery workflow from
request to verified result. It turns a user task into a reviewed specification,
an approved plan, bounded implementation work, review, and final proof, so
agents finish the job instead of stopping at a patch.

The workflow is provider-neutral. Codex, Claude Code, Qwen Code, Goose,
OpenInterpreter, Pi, Grok Build, or another CLI can follow the same lifecycle,
while provider commands, model choice, and secret handling stay in adapters or
host-local profiles.

## Quick start

From a source checkout:

```bash
python -m pip install -e .
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
agent-lifecycle start --adapter codex --text "Draft a reviewed implementation plan"
```

The official [PyPI package](https://pypi.org/project/agent-lifecycle-kit/) supports Python 3.11-3.14.
Install the exact release with `python -m pip install agent-lifecycle-kit==1.53.0`.

For a short walkthrough, use [Quickstart](docs/guides/quickstart.md) and the [Lifecycle cookbook](docs/guides/lifecycle-cookbook.md). For structure and positioning, see [System architecture](docs/architecture/system-architecture.md) and [Project comparison](docs/reference/project-comparison.md). Russian documentation starts at [Документация на русском](docs/ru/README.md).

## What it gives you

- A finish-oriented lifecycle: plan, execute, review, and prove the result.
- One process for different CLIs: adapter-specific commands stay outside the
  core, and new adapters can be added without changing lifecycle schemas.
- Small-model friendly packets: compact context, clear next actions, and
  deterministic checks for local or cheaper models.
- Quality without overengineering: optional profiles turn on only when risk or
  task type requires them.
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
- Optional Review Mesh covers leader-draft review, parallel research synthesis
  and audit panels. The advisor can suggest a mode; `review-mesh prepare`
  creates local reviewer packets; opted-in plans can require
  assignment/result/synthesis/quorum receipts, but ALK core does not start hosts.

### Routing and resource control

- Compact context profiles, small-model packets, objective snapshots, and
  local quality-cost learning help choose the lightest safe mode.
- Phase resource measurements reuse the usage export envelope for tokens,
  duration, and resource counters without mandatory monetary accounting.
- Usage/session exports include tokens, resources, receipt digests, and optional
  host-reported `cost_usd`.

### Security and containment

- Neutrality filters use host-supplied deny rules to keep local paths, secrets, trust roots, and signing keys out of portable artifacts.
- Host env files require explicit `--host-env-allow`; receipts store redacted metadata, and generic descriptor-driven native launch is blocked before process creation.
- Imports, diagnostics, and usage exports redact local paths and common secret markers before validation.
- Sandbox receipts separate runtime filesystem, network, process, and environment containment from git write-scope.
- Release security gates reject leaked local paths, credentials, and unsupported adapter or production claims.

### Adapters and interop

- Adapter contracts keep host-specific projections separate from lifecycle
  schemas.
- New CLI hosts start as adapters: descriptor, command projection, environment
  boundary, and verification evidence live outside the lifecycle core.
- Adapter capability checks and progress bridge support compare live receipts
  and display lifecycle state without automatic maturity changes.
- Import mappers and issue-to-spec intake treat external workflows, agent
  dialects, and tickets as untrusted draft inputs.
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

## Adapter maturity

`EXPERIMENTAL` means offline checks exist; bounded live host conformance and
usage/resource calibration are still required before `VERIFIED`. The verified
claim is host-specific and also requires accepted redacted evidence and
lifecycle final proof for the tested host range. New hosts can be added as
adapters first and promoted only for the exact CLI/version/provider binding that
has evidence. Monetary accounting is required only for metered modes.

| Host | Current claim |
| --- | --- |
| Codex | `VERIFIED` for Codex CLI 0.145.0. Public Plugins Directory approval is not claimed. |
| Claude Code | `VERIFIED` for Claude Code 2.1.220. Official directory approval is not claimed. |
| OpenCode | `VERIFIED` for OpenCode CLI 1.18.9. npm publication is not claimed. |
| Hermes | `VERIFIED` for Hermes Agent v0.19.0. Public directory approval is not claimed. |
| Qwen Code | `VERIFIED` for Qwen Code 0.21.0 on the tested host-local provider/model binding. Public package approval is not claimed. |
| Cursor | `EXPERIMENTAL`; local safe inspection passed, but accepted live receipts are incomplete. |
| Gemini CLI | `EXPERIMENTAL`; local live canary is blocked by the current Gemini Code Assist tier. |
| Goose | `VERIFIED` for Goose 1.45.0 on the tested host-local provider/model binding. Public directory approval is not claimed. |
| Kimi Code | `EXPERIMENTAL`; live proof requires a configured provider and model alias. |
| Grok Build | `VERIFIED` for Grok Build 0.2.117 on the tested host-local provider/model binding. Public directory approval is not claimed. |
| OpenInterpreter | `VERIFIED` for `interpreter` 0.0.34 on the tested host-local provider/model binding. Public directory approval is not claimed. |
| Pi | `VERIFIED` for Pi 0.83.0 on the tested host-local provider/model binding. Public directory approval is not claimed. |

Adapter installation and maturity details live in [Adapter install](docs/adapters/install.md) and [Adapter support matrix](docs/adapters/support-matrix.md).

## Contract map

The public lifecycle surface is schema-backed. Full stable schema ids, compatibility rules, runner recovery, cross-check, Review Mesh, Bug Forensics and usage export details are listed in [Public contracts](docs/reference/public-contracts.md).

## Design boundaries

- The core stays provider-neutral. Concrete host commands and model bindings
  belong to adapters or host-local profiles.
- New CLIs are integrated through adapters: descriptor, command projection,
  environment boundary, and verification evidence. The lifecycle schemas remain
  stable while host support grows.
- Small models get compact packets, deterministic checks, and explicit
  next-action lists instead of long narrative state.
- Larger models keep the same gates; better reasoning does not bypass evidence.
- Public release claims are limited to tracked source files and redacted
  evidence summaries.
- External dialect imports and retrieved episodes are context aids only; they
  do not replace reviewed ALK source-of-truth artifacts.
- Optional cross-check, Review Mesh and runner recovery receipts add evidence
  only when a task or plan requests them; they are not default multi-model execution.

## Documentation

- Start: [English documentation](docs/README.md), [Русская документация](docs/ru/README.md), [Quickstart](docs/guides/quickstart.md), [Lifecycle cookbook](docs/guides/lifecycle-cookbook.md), and [Code review workflows](docs/guides/code-review-workflows.md).
- Planning and adapters: [Issue to specification drafts](docs/guides/issue-to-spec.md), [Adapter install](docs/adapters/install.md), and [Adapter support matrix](docs/adapters/support-matrix.md).
- Reference: [System architecture](docs/architecture/system-architecture.md), [CLI reference](docs/reference/cli.md), [Source of truth](docs/reference/source-of-truth.md), [Managed lifecycle runner](docs/reference/managed-lifecycle-runner.md), [Managed adapter sessions](docs/reference/managed-adapter-sessions.md), [Implementation audit](docs/reference/implementation-audit.md), [Plan completeness](docs/reference/plan-completeness.md), [Public contracts](docs/reference/public-contracts.md), and [Readiness diagnostics](docs/reference/readiness-diagnostics.md).
- Quality and resources: [Small-model packets](docs/reference/small-model-packets.md), [model routing](docs/reference/model-routing.md), [adaptive policy](docs/reference/adaptive-lifecycle-policy.md), [quality-cost learning](docs/reference/quality-cost-learning.md), [lifecycle cost accounting](docs/reference/lifecycle-cost.md), [Usage export](docs/reference/usage-export.md), and [Evidence integrity](docs/reference/evidence-integrity.md).
- Profiles and operations: [Read-only status views](docs/reference/read-only-status-view.md), [Adapter progress bridge](docs/reference/automatic-progress-bridge.md), [Sandbox boundaries](docs/reference/sandbox-boundaries.md), [Import mappers](docs/reference/import-mappers.md), [Episode retrieval](docs/reference/episode-retrieval.md), [Runner recovery](docs/reference/runner-recovery.md), [Cross-check profile](docs/reference/cross-check-profile.md), [Review Mesh](docs/reference/review-mesh.md), [Bug Forensics profile](docs/reference/bug-forensics.md), and [Bug Forensics context budget](docs/reference/bug-forensics-context-budget.md).
- Release assets: [Task templates](templates/tasks/README.md) and [Release security](docs/security/release-security.md).

Apache-2.0. See [LICENSE](LICENSE).
