# Release Matrix And Evidence Aggregation

## Required Matrix

Every production release runs all nine legs against one source revision,
dependency-lock digest and command-set digest.

| Leg id | Operating system image | Architecture | Interpreter |
| --- | --- | --- | --- |
| linux-py311 | Ubuntu 24.04 | x86_64 | CPython 3.11 |
| linux-py312 | Ubuntu 24.04 | x86_64 | CPython 3.12 |
| linux-py313 | Ubuntu 24.04 | x86_64 | CPython 3.13 |
| macos-py311 | macOS 14 | arm64 | CPython 3.11 |
| macos-py312 | macOS 14 | arm64 | CPython 3.12 |
| macos-py313 | macOS 14 | arm64 | CPython 3.13 |
| windows-py311 | Windows Server 2022 | x86_64 | CPython 3.11 |
| windows-py312 | Windows Server 2022 | x86_64 | CPython 3.12 |
| windows-py313 | Windows Server 2022 | x86_64 | CPython 3.13 |

## Per-Leg Receipt

Before any leg starts, the controller must verify the signed external
`agent-lifecycle-ci-matrix-authority.v2` allowlist described in
`12-authority-and-environment-profiles.md`. Its digest and authority
fingerprint are frozen into the run state for WS-14. A leg may prove only the
profile already assigned to its id; it cannot select a runner image, toolchain
or trust authority from inside its own receipt.

The CI environment, not a semantic agent, signs each bounded receipt. It binds:

- leg id, source revision and dependency-lock digest;
- immutable runner image id, architecture and complete interpreter identity;
- bounded toolchain identity and canonical command-set digest;
- the non-recursive `candidatePayloadInventoryDigest` over payload bytes and
  the candidate payload object-manifest digest;
- start and finish times, CI authority fingerprint and Ed25519 signature.

The candidate object manifest, rather than a future final inventory, binds the
wheel, source-distribution, adapter-bundle, SBOM, notices and generated
documentation object identities. Secret or origin-specific values are
forbidden.

Self-authored worker JSON is not a matrix receipt. Each leg has a separate
evidence id, path and receipt path in the plan manifest.

## Aggregate Rule

The aggregate accepts exactly the nine declared leg ids, the one
controller-approved allowlist digest and one identical
`candidatePayloadInventoryDigest`. It fails closed for a missing or duplicate
leg, age over 24 hours, signature failure, unknown CI authority,
source/lock/command/allowlist mismatch, incompatible toolchain, unexpected
artifact identity, skipped gate, non-pass verdict or candidate digest mismatch.
The aggregate is content-addressed and signed and binds the exact leg-receipt
identity set plus the accepted authority fingerprint. It must not contain or
claim a future `finalInventoryDigest`; only release assembly can create that
identity.

Local single-host commands are preflight evidence only. They cannot satisfy
`AC-PLATFORM-MATRIX` or promote a production release.

## Immutable Release Inventory Handoff

After the aggregate and live calibration pass, WS-14 performs two isolated
clean builds. Each build must reproduce the aggregate's
`candidatePayloadInventoryDigest`. Candidate identity covers payload bytes
only; it deliberately excludes matrix receipts, the aggregate, final inventory,
commit marker, provenance and later neutrality/release receipts.

Assembly stages the complete release unit under one unique same-filesystem
transaction. Its closed inventory body binds candidate object paths, hashes,
sizes and modes; matrix aggregate; both build identities; source, dependency
lock, toolchain and command identities; license results; and provenance. It
excludes its own digest, inventory file, commit marker and later verification
receipts. Assembly computes the separate `finalInventoryDigest`, writes
`COMMITTED.json` last in staging, fsyncs, then atomically renames with no replace
to `release/generations/{finalInventoryDigest}`. Orphan staging and mutable
aliases are never authoritative.

The operation-scoped assembly receipt binds the exact committed generation.
Release neutrality and the final `--no-build` verifier consume that same
receipt and traverse the same generation read-only. Both rebind source, lock,
toolchain, matrix, candidate and final digests; the verifier additionally proves
pre/post Merkle equality. Occupancy, crash residue, substitution, post-scan
mutation, rebuild or any digest mismatch blocks release even if all nine legs
passed.
