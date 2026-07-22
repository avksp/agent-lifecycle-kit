# Authority And Environment Profiles

This revision explains the normalized public contract inputs used by the five
offline adapter workstreams and the identities required from the external CI
matrix authority. It contains no copied source documentation and no live-host
claim. A later source refresh requires specification reopen, independent
review and refreeze.

The canonical machine authority for adapter inputs is
`adapter-contract-inventory-r02.json`; the canonical matrix authority is
`ci-matrix-profile.v2.json`; release generation is governed by
`release-assembly-profile.v1.json`; the canonical runtime neutrality authority
is `neutrality-authority-profile.v3.json`; terminal completion is governed by
`final-proof-authority-profile.v2.json`. A mismatch with this prose fails
closed.

## Runtime Neutrality Authority

Profile id: `neutrality-write-once-authority`, version `3.0.0`.

The host supplies only these external environment names to the controller:

- `AGENT_LIFECYCLE_NEUTRALITY_DENY_AUTHORITY` — path to the signed external
  deny authority;
- `AGENT_LIFECYCLE_NEUTRALITY_TRUST_ROOT` — path to the external public trust
  root;
- `AGENT_LIFECYCLE_NEUTRALITY_SIGNING_KEY` — producer-only path to the private
  Ed25519 signing key;
- `AGENT_LIFECYCLE_NEUTRALITY_SIGNER_FINGERPRINT` — expected public signer
  fingerprint.

Each external path must be absolute and point to a bounded regular file outside
the workspace, artifact root, Git directory and release root. Every component
is opened relative to a verified parent handle with no-follow semantics;
symlinks, reparse points, hardlink count greater than one, identity/content
changes, malformed or stale authority, oversize files, bad signatures and
fingerprint mismatches fail closed. Producer and verifier read only from the
opened stable handle; only producer receives the signing key. These exact
external-input negatives are mandatory conformance cases.

The frozen producer and verifier invoke
`python src/agent_lifecycle/neutrality/gate.py` directly, not a shell. Both bind
gate/run/package/task/attempt/phase/operation/plan/source and the complete
current-tree scope. Each operation freezes ordered exact-path descriptors for
primary artifacts and a detached commit receipt. Paths are portable,
repository-relative, unique and absent at scan and immediately before
create-if-absent publication. Primary content identities enter the signed
claims and publish first; the detached Ed25519 receipt publishes last. A fully
committed replay is read-only and byte-identical. Partial publication,
occupancy, reuse, substitution, aliasing or creation races fail closed and are
scanned by later operations.

Only the current operation's exact output set is removed from subject
enumeration; it is signed into scope and does not count as skipped. Previous
outputs remain scanned. Producer and verifier recompute the same operation and
primary manifests, projection, scope-profile, archive-policy, external
authority, worktree, Git-object-set, release-inventory when applicable, scope,
subject, authority and claims identities. Durable output may contain only
closed schemas, versions, digests, public fingerprint, signature, exact output
paths, zero counters, timestamps and lineage. Rule values, trust material,
private keys, matched fragments and credentials are forbidden.

Required zero counters are: `findings`, `skippedInputs`, `opaqueInputs`,
`readRaces`, `incompleteScans`, `unsupportedArchives`,
`archiveLimitBreaches`, `occupiedOutputConflicts` and `pathAliasConflicts`.
Supported archive formats are detected by magic and limited to zip, tar and
tar-gzip. Numeric limits are frozen exactly as follows:

| Limit | Maximum |
| --- | ---: |
| nesting depth | 4 |
| archives per subject | 1000 |
| entries per archive | 10000 |
| entries per subject | 100000 |
| compressed bytes per archive | 536870912 |
| expanded bytes per archive | 2147483648 |
| expanded bytes per entry | 268435456 |
| expanded bytes per subject | 4294967296 |
| compression ratio | 100 |
| path UTF-8 bytes | 4096 |

Encrypted archives, unsupported compression, duplicate normalized paths,
case-fold collisions, traversal/device/ADS/trailing-dot-or-space paths and
symlink, hardlink, device, FIFO, socket or sparse entries fail closed.

## Atomic Release Assembly Authority

Profile id: `atomic-content-addressed-release-generation`, version `1.0.0`.

Every one of the nine CI legs and the authenticated aggregate bind one
non-recursive `candidatePayloadInventoryDigest` over candidate payload bytes
only. Both isolated clean assembly builds must reproduce that exact candidate
digest. Matrix receipts and aggregate are forbidden from claiming the separate
future `finalInventoryDigest`.

Assembly creates one unique same-filesystem staging transaction, writes all
objects create-if-absent/no-replace, computes `finalInventoryDigest` from the
closed canonical final inventory body, writes `COMMITTED.json` last, fsyncs and
atomically renames the staging directory with no replace to
`release/generations/{finalInventoryDigest}`. An orphan, mutable alias or
occupied/mismatched generation is not authoritative. The detached assembly
receipt binds the exact committed generation; release neutrality and the
read-only `--no-build` verifier must consume that same receipt and prove stable
pre/post Merkle identity.

## Controller Final Proof Authority

Profile id: `controller-finalization-transaction`, version `2.0.0`.

The terminal audit may bind predecessors and its own pre-launch gate only and
must return `READY_FOR_FINALIZATION`. The controller then verifies the exact
WS-15 post-attempt gate and independent accepted review, then enters
`AWAITING_FINAL_PROOF` bound to the expected state revision/digest, WAL
predecessor and a preallocated finalization operation id. Finalization
neutrality runs only after that accepted review. Its operation-output manifest
projects only its exact new primary artifact and detached commit receipt while
the accepted review, all prior artifacts, the future proof path and predecessor
WAL/state are scan inputs. The proof, predecessor-bound WAL append and
expected-revision state replacement belong to a separate closed canonical
controller finalization output set whose digest is bound by both the
neutrality claims and proof body.

The proof is acyclic. Its closed canonical body contains normalized identities
but no body digest, envelope digest or artifact path. `proofBodyDigest` is
domain-separated and stored only in the signed write-once envelope;
`envelopeDigest` is separately domain-separated and stored only in the
completion WAL record and `COMPLETE` state. The controller publishes the
envelope create-if-absent, appends and fsyncs one idempotency-keyed WAL record,
then atomically replaces state by expected-revision CAS. A crash before proof,
after proof but before WAL, after WAL but before state, or after state resumes
the same operation and verifies the same durable identities. Identical replay
returns the existing proof/state; conflicting replay or any plan, source,
profile, review, gate, inventory or change-set drift blocks completion. No
additional post-proof neutrality gate is allowed because it would recreate a
self-dependent cycle.

## Adapter Contract Inventory

Each offline adapter targets exactly one normalized contract revision. The
official source capture SHA-256 is provenance for that revision; adapter tests
consume the normalized facts below and never fetch a source at task runtime.
The offline `contractCompatibilityRange` is the closed interval containing
that one revision. `hostTestedRange` is absent at `EXPERIMENTAL` maturity and
may be populated only by the optional live-promotion process.

### codex

- contract id: `codex-plugin-contract-2026-07-15`;
- range: minimum and maximum
  `codex-plugin-contract-2026-07-15`;
- official source: `https://learn.chatgpt.com/docs/build-plugins.md`;
- source capture SHA-256:
  `71d34334545be1dcbf5e3dd81195b722ac030840ec61a057a7fc5e68fcef79cc`;
- normalized facts: plugin manifest is
  `.codex-plugin/plugin.json`; reusable skills are under `skills/`; a plugin
  may package skills and other declared extension components; unsupported
  runtime operations remain explicit;
- redistribution class: reference-only URI and digest; no source text is
  redistributed.

### claude

- contract id: `claude-plugin-contract-2026-07-15`;
- range: minimum and maximum
  `claude-plugin-contract-2026-07-15`;
- official source: `https://code.claude.com/docs/en/plugins.md`;
- source capture SHA-256:
  `1e47c49339d2705edca706b78843b8ddad7ed1017e569a0a239ab8e326754c95`;
- normalized facts: plugin manifest is
  `.claude-plugin/plugin.json`; skills, agents, hooks and MCP configuration
  are plugin-root components; `--plugin-dir` is a development discovery
  route; unavailable runtime operations remain explicit;
- redistribution class: reference-only URI and digest; no source text is
  redistributed.

### cursor

- contract id: `cursor-agent-contract-2026-07-15`;
- range: minimum and maximum `cursor-agent-contract-2026-07-15`;
- official sources: `https://docs.cursor.com/context/rules-for-ai` and
  `https://docs.cursor.com/en/cli/using`;
- official page-shell capture SHA-256:
  `34efb96589c7f1230ca165dea4c175053bcc83cbb945aafdb7531da63cfca10a`;
- normalized facts: project rules are `.mdc` files under `.cursor/rules`;
  `AGENTS.md` is a supported root instruction surface; CLI print mode supports
  structured output; unavailable lifecycle operations remain explicit;
- redistribution class: reference-only URIs and digest; no source text is
  redistributed.

The Cursor source is a client-rendered official page and both URLs currently
return the same page shell. Its capture digest is provenance only. The
machine-readable normalized-facts digest, independent specification review and
immutable plan lock form the offline authority. No claim is made that the page
shell is rendered documentation or a standalone schema.

### opencode

- contract id: `opencode-extension-contract-2026-07-15`;
- range: minimum and maximum
  `opencode-extension-contract-2026-07-15`;
- official sources: `https://opencode.ai/docs/plugins.md`,
  `https://opencode.ai/docs/skills.md` and
  `https://opencode.ai/docs/agents.md`;
- ordered source capture SHA-256 values:
  `ab99892a03931c7d7cb36f93beba067346492cb9adae0f263fb6ac83f83391bb`,
  `0cc6d2ebeece718df41fdec0164d406b1fa9bd60fd5b46c94fc0fab63ddd5b93`
  and
  `7b7dfc8ca2fc363358d6c6f4625bc13d8386942f9b64b0fcaa711a5aeee56074`;
- normalized facts: plugins expose extension hooks, skills are discovered from
  `SKILL.md` roots, agents have declared modes and permissions, and
  unavailable lifecycle operations remain explicit;
- redistribution class: reference-only URIs and digests; no source text is
  redistributed.

### hermes

- contract id: `hermes-skills-contract-2026-07-22`;
- range: minimum and maximum `hermes-skills-contract-2026-07-22`;
- official sources:
  `https://hermes-agent.nousresearch.com/docs/user-guide/features/skills`
  and `https://hermes-agent.nousresearch.com/docs/`;
- ordered source capture SHA-256 values:
  `5d58c9c4d57fc6ce102b030c46c8896b83f877a9f0f5742ee1f44490ea0bd955`
  and
  `b40b6eaad836c5897ad3959ed8d213938f5ab28471a4319d7c729b762b84d6a4`;
- normalized facts: installed skills live under `~/.hermes/skills/`,
  external skill directories can be scanned alongside the local skill root,
  skills are invokable as slash commands, and unavailable lifecycle operations
  remain explicit;
- redistribution class: reference-only URIs and digests; no source text is
  redistributed.

## CI Matrix Authority Profile

Profile id: `agent-lifecycle-ci-matrix-authority.v2`.

Before WS-14 starts, the host must provide a signed external allowlist and its
SHA-256 through controller-owned configuration. The allowlist contains exactly
the nine leg ids frozen in `10-release-matrix.md` and, for each leg:

- immutable runner image or VM image digest;
- architecture and complete CPython patch-version interval;
- package-builder, lock resolver, test runner, schema validator, neutrality
  scanner and supply-chain scanner identities with bounded versions;
- canonical command-set digest;
- CI signing authority fingerprint and receipt lifetime;
- permitted network and secret scopes.

The controller records only the allowlist digest, authority fingerprint,
expiry, leg-profile ids and command-set digest in durable run state. It never
copies credentials or private rules into the plan, packet or evidence payload.
WS-14 is not
launchable until an independent controller gate verifies the signature,
freshness and exact nine-leg coverage. Each CI receipt then proves conformance
to that already accepted digest; a receipt cannot choose or widen its own
environment profile. Every receipt additionally binds one
`candidatePayloadInventoryDigest` and candidate object-manifest digest. All
nine values and the signed aggregate value must be identical; the aggregate
binds the exact leg set and is forbidden from containing a
`finalInventoryDigest`.

For the first release, the externally supplied allowlist is execution input,
not a plan mutation. Changing a leg id, operating-system family, architecture,
Python minor, required tool class or trust model still requires specification
reopen and refreeze.
