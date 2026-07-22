# Developer Overview

## What This Plan Implements And Why

This plan creates the first standalone release of Agent Lifecycle Kit: a
project-neutral, model-neutral and surface-adaptable system for turning a
request into a reviewed specification, a frozen implementation plan, bounded
agent tasks, independently reviewed results and a final evidence-backed
completion verdict.

The standalone repository must be independently installable. It must never
depend on, describe or embed information from any source application
repository. Source-specific policy remains outside this repository.

## Expected User-Facing Behavior

Users can install one release and run the same lifecycle on supported agent
surfaces. The lifecycle asks only blocking questions, selects an SDD tier,
iterates independent reviews, freezes the plan, executes dependency-safe task
packets, audits each attempt and completes only after a strict final audit.

Every adapter publishes an explicit maturity level. All five required adapter
tasks run offline and can produce release-eligible `EXPERIMENTAL` bundles.
Unsupported capabilities fail closed; only a separate authorized live
full-operation proof can mark an adapter `VERIFIED`.

## Developer-Facing Impact

The repository will contain an importable Python package, stable CLI,
versioned schemas, five thin semantic skills, isolated surface adapters,
synthetic fixtures/evals, conformance suites and deterministic release tools.
Project profiles, project commands and project documentation are intentionally
absent.

## Operational Impact

Workflow state is durable and resumable. Immutable specifications, plan locks
and task packet identities remain separate from mutable run state. Every
external operation has a finite timeout, every retry has a budget, and release
claims require content-addressed evidence.

Release validation is intentionally ordered. Every matrix leg and two clean
builds bind the same non-recursive `candidatePayloadInventoryDigest`. WS-14
then publishes one write-once, content-addressed generation whose separate
`finalInventoryDigest` covers the closed release unit. Neutrality and final
verification consume that committed generation read-only without rebuilding.

## Architecture And Operational Constraints

- Core semantics cannot contain provider names, native agent APIs or model
  identifiers.
- Adapter discovery, plugin manifests, approvals, delegation and model routing
  stay under `adapters/{surface-id}/`.
- A change-set provider interface separates lifecycle semantics from Git;
  `git-worktree-v1` is the initial implementation, not a core invariant.
- The neutrality gate scans tracked, staged, untracked and ignored files,
  logical Git history, unreachable objects and every generated archive.
  `neutrality-authority-profile.v3.json` freezes one `NEUTRALITY_*` external
  authority contract, no-follow stable reads, numeric archive depth/count/byte
  and ratio bounds, and exact operation-bound output descriptors. Primary
  artifacts are content-bound and published create-if-absent; the detached
  signed receipt is written last as the commit marker. Every output path must
  be absent for a new operation, a committed identical replay is read-only,
  and occupancy, alias, partial publication, substitution or race fails
  closed. External deny/trust/signing inputs remain outside workspace, Git,
  artifact and release roots. Only redacted schemas, digests, signer
  fingerprint, signature, counters and lineage enter durable proof.
- Python 3.11 through 3.13 is the initial runtime. Dependencies are locked for
  releases and verified on Linux, macOS and Windows.
- Resource, path, symlink, subprocess and evidence limits fail closed.

## Included Scope

- Neutral lifecycle core and CLI.
- SDD S0/S1/S2 contracts and deterministic validators.
- Durable orchestration, compact controller output and end-to-end stage usage
  accounting.
- Five portable lifecycle skills.
- Adapter contract plus Codex, Claude, Cursor, Hermes and OpenCode overlays
  with honest maturity declarations.
- Fully synthetic conformance fixtures and evals.
- Apache-2.0 release metadata, dependency lock, SBOM/provenance tooling and
  deterministic release inventory.
- Compact controller projections, prompt envelopes and a host-attested usage
  ledger spanning every semantic lifecycle stage.
- External provider-neutral routing profiles that may select one or different
  host models per stage without placing model names in core contracts.
- Frozen S0/S1/S2 resource budgets and cost-regression rules.
- Authenticated nine-leg Linux, macOS and Windows release evidence under
  `ci-matrix-profile.v2.json`, with every leg bound to the same non-recursive
  candidate payload identity.

## Excluded Or Deferred Scope

- Any application-specific profile, path, command, document or fixture.
- Importing source-repository history.
- Claiming a surface as verified without host conformance evidence.
- Publishing a remote release or signing with a real production key during
  this implementation package.
- Additional surface adapters beyond the initial five; they use the same
  versioned adapter contract in later releases.

## How Developers Should Read And Review This Package

Read product specification r06 first, then this overview, architecture
contracts, workstreams/DAG, validation matrix and acceptance checklist. Treat
`plan.manifest.json` as authority for task ownership and evidence. Worker
prompts are operational projections of the frozen plan, not an alternative
source of truth.

## Final Readiness Rule

The release is ready only when every required task is independently accepted
with no unresolved Medium, High or Blocker finding, neutrality reports zero
violations, conformance passes and the committed release generation verifies.
The independent terminal audit returns `READY_FOR_FINALIZATION`; after its
post-attempt neutrality gate and independent task review, the controller enters
`AWAITING_FINAL_PROOF`. It then runs finalization neutrality over the accepted
review and every prior artifact. Only the acyclic, fixed-operation-path proof,
idempotent fsynced WAL append and expected-revision CAS state replacement
defined by `final-proof-authority-profile.v2.json` may transition the exact
frozen run to `COMPLETE`.

Specification r06 and plan r06 remain candidates. Neither this overview nor
the new profiles constitutes independent review or freeze authority.
