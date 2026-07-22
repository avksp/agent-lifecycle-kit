# Architecture Contracts

## Layer And Module Ownership

- `src/agent_lifecycle/schemas/`: canonical JSON schemas. The CLI can list,
  show and export them; generated copies are never authoritative.
- `src/agent_lifecycle/`: deterministic core, provider interfaces and CLI
  implementation. It does not import adapter packages.
- `skills/`: exactly five thin semantic skills. They refer to stable CLI and
  schemas rather than embedding provider launch syntax.
- `adapters/{surface-id}/`: discovery metadata, plugin manifests, host capability
  mapping, model routing and operation execution.
- `conformance/`, `fixtures/synthetic/`, `evals/synthetic/`: inventoried,
  synthetic-only lifecycle and adapter verification.
- `tools/release/`: reproducible packaging and release verification; never the
  canonical lifecycle semantics.
- `release/`: declarative inventory, compatibility matrix and provenance
  policy. Generated distributions and private receipts remain outside Git.

## Interface Sketches

```text
request
  -> lifecycle planner/reviewer contracts
  -> immutable specification + plan lock
  -> deterministic task packet compiler
  -> workflow controller nextAction
  -> surface adapter operation
  -> normalized result/review/usage receipt
  -> workflow controller transition
  -> final integrated proof snapshot
```

Stable extension interfaces:

- `ChangeSetProvider`: baseline identity, changed-file enumeration and tree
  snapshot without making Git a lifecycle invariant.
- `SurfaceAdapter`: capability declaration and typed lifecycle operations.
- `UsageAttestor`: raw provider counters plus normalized billable totals and
  stage identity.
- `ArtifactStore`: content-addressed reads/writes under workspace confinement.
- `PromptEnvelope`: ordered content identities, capability profile, rendered
  prompt hash, context bytes, host token estimate and cache identity.
- `CapabilityRouter`: stage/role to ordered external profile selection that
  preserves mandatory capabilities and independence class or fails closed.

## Performance And Runtime Placement

- Deterministic validators run before semantic agents.
- Controller responses are compact by default; full state remains on disk and
  is returned only on explicit request.
- Skill/reference loading is stage-routed. Workers receive one task packet,
  relevant contracts, scoped diff and evidence digest.
- Resource ceilings cover authority JSON, opaque artifacts, subprocess output,
  per-call and cumulative-per-run context, per-task and per-run logical
  semantic calls, tokens, task/run wall time, retries and event journals. One
  semantic iteration permits zero or one logical semantic call; fallback,
  review, remediation and cache reuse never reset task or run counters.

## Compatibility, Failure, Retry And Rollback Semantics

- Schemas use explicit versions; incompatible changes require a new version and
  migration/conformance coverage.
- Mutations use expected revision and idempotent operation ids.
- Timeouts, missing capabilities, stale authority, cancellation uncertainty
  and unavailable atomic exchange fail closed.
- Installation and packet publication stage content before atomic replacement;
  failure preserves the prior valid release/state.
- Release assembly stages one unique transaction and publishes the complete
  generation with a same-filesystem no-replace rename; a pre-commit orphan or
  mutable alias is never an accepted release identity.
- Release generation is reproducible from the locked source revision.

## Security And Permission Constraints

- Workspace reads reject symlinks/path traversal and validate stable file
  identity.
- Host permissions remain authoritative; automatic mode never expands them.
- Secrets, credentials and external deny terms are redacted from prompts,
  logs, state and evidence.
- Adapter maturity cannot be `verified` from self-authored JSON alone; host
  attestations and conformance are required.
- Neutrality authority uses detached Ed25519 verification. Deny authority,
  trust root and signing inputs are bounded regular files outside workspace,
  Git, artifact and release roots, opened no-follow and checked for stable
  identity. Production private keys are producer-only host inputs; accepted
  redacted attestations bind signer fingerprint, subject/scope hashes and
  freshness without persisting authority contents or secret material.

## Controller Neutrality Gate

The immutable manifest defines one controller-owned gate command and receipt
template under `workflow/gates/{gateId}/{taskId}/attempt-{attempt}/`. The
controller runs it before
every downstream launch and after every attempt. Launch and acceptance bind
the latest receipt to the exact source/tree subject, external authority digest,
trust-root fingerprint and current-tree scope. Workers never receive deny
values or signing keys. `neutrality-authority-profile.v3.json` freezes the
single `AGENT_LIFECYCLE_NEUTRALITY_*` environment contract, signature, zero
counters, freshness, redaction, subject projection and numeric archive limits.

WS-14 adds an ordered pre-launch chain. A generic current-tree receipt precedes
the release-authority preflight; that preflight verifies and binds the external
CI allowlist, benchmark baseline and live-calibration profile; a dedicated
release-launch neutrality gate runs last so the newly written authority receipt
is included in the launch subject. Gate dependencies are frozen, acyclic and
enforced by the controller.

Every current-operation output has one canonical operation-bound descriptor
and a portable repository-relative path that must be absent at scan and
immediately before publication. Non-self-referential primary artifacts publish
create-if-absent first and their content identities enter domain-separated JCS
claims; the detached signed receipt publishes last as the commit marker.
Previous and partial outputs remain scanned. Only a committed byte-identical
same-operation replay is read-only; occupancy, reuse, path alias, substitution,
archive breach or stable-read race fails closed. Producer and verifier
recompute the same projection and digest set.

## Release Assembly And Terminal Proof

WS-14 has one owner and an explicit data-dependent sequence. Every authenticated
matrix leg and its aggregate bind the same non-recursive
`candidatePayloadInventoryDigest`; two isolated clean builds must reproduce it.
`release-assembly-profile.v1.json` then stages the complete release unit,
computes a separate `finalInventoryDigest`, writes its commit marker last,
fsyncs and publishes the whole generation atomically to a content-addressed
path. Neutrality and `--no-build` verification consume that exact committed
generation read-only and prove pre/post Merkle equality.

WS-15 produces an independent `READY_FOR_FINALIZATION` audit covering all
predecessors and its pre-launch gate. Its post-attempt gate then covers that
audit and its independent reviewer accepts the attempt. The controller enters
`AWAITING_FINAL_PROOF` bound to the exact predecessor state, WAL and a fixed
operation id. Finalization neutrality scans the accepted terminal review and
all prior artifacts while its operation-output manifest projects only its own
primary artifact and detached commit receipt. The future proof path and the
predecessor WAL/state remain scan inputs. A separate canonical
`controllerFinalizationOutputSetDigest` binds the create-no-replace proof,
predecessor-bound WAL append and expected-revision state replacement. Under
`final-proof-authority-profile.v2.json`, a closed proof body has no
derived/self digest; its envelope carries `proofBodyDigest`, while only
`envelopeDigest` enters WAL/state. Create-no-replace proof publication, one
idempotent fsynced WAL append and expected-revision CAS replacement form the
only transition to `COMPLETE`; no post-proof neutrality gate reopens the cycle.

## Product Budgets And Release Matrix

`agent-lifecycle-budget-profile.v1.json` is the immutable shipped budget
authority; manifest orchestration ceilings govern only this implementation
run. `10-release-matrix.md`, `ci-matrix-profile.v2.json` and
`12-authority-and-environment-profiles.md` define nine distinct CI-owned legs,
external dispatch/trust input, non-recursive candidate payload identity and
aggregation.
`11-adapter-compatibility-and-maturity.md` plus
`adapter-contract-inventory-r02.json` make all required adapter work offline
and reserve live runtime use for optional promotion.

## Forbidden Shortcuts

- No project-specific profile, path, command, document, fixture or identifier.
- No provider/model/native-agent tokens in core task packets or core skills.
- No direct imports from core into adapters or between adapters.
- No manually edited frozen specification, plan lock or compiled packet.
- No prose-only readiness, evidence-existence-only checks or self-review.
- No copying of external samples/evals; all fixtures are authored synthetically.
- No hard-coded default branch or repository root.
- No committed origin-specific deny set, private receipt or detailed matching
  fragment.
- No reused operation-output path, overwrite fallback, mutable release alias,
  self-referential digest or post-proof validation cycle.
- No silent model/profile fallback, capability weakening or maturity promotion.
