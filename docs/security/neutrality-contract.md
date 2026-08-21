# Neutrality authority contract

Release 1.75 signs the complete security subject: claims, operation and the
primary artifact identity are verified together. Omitting or replacing one of
these fields cannot turn an unrelated report into valid neutrality proof.

The neutrality boundary prevents origin-specific repository information,
secrets, injected deny values, trust roots, and signing keys from becoming part
of the portable kit.

The committed repository contains only generic policy and verifier code. The
actual deny authority and signing material are supplied by the host at runtime
through environment variables:

- `AGENT_LIFECYCLE_NEUTRALITY_DENY_AUTHORITY`
- `AGENT_LIFECYCLE_NEUTRALITY_TRUST_ROOT`
- `AGENT_LIFECYCLE_NEUTRALITY_SIGNING_KEY`
- `AGENT_LIFECYCLE_NEUTRALITY_SIGNER_FINGERPRINT`

All paths must be absolute regular files outside the workspace, artifact root,
Git directory, and release root. Symlinks, hard-linked files, unstable reads,
stale authority files, malformed JSON, unknown signer fingerprints, and bad
Ed25519 signatures fail closed.

Durable outputs may contain schema versions, digests, public signer
fingerprints, signatures, exact output paths, zero-result counters, timestamps,
and lifecycle identifiers. They must not contain deny rule values, private key
material, trust-root material, credentials, or matched source fragments.

The producer writes the primary report first with create-no-replace semantics
and publishes a detached signed receipt last as the commit marker. A
same-operation replay is read-only and byte-identical; occupied, substituted,
partial, aliased, or raced outputs fail closed.

## Completeness counters

A report is eligible for signing, and an existing signed receipt is eligible
for reuse, only when every required counter is present as the integer zero:
`findings`, `skippedInputs`, `opaqueInputs`, `readRaces`, `incompleteScans`,
`unsupportedArchives`, `archiveLimitBreaches`, `occupiedOutputConflicts`, and
`pathAliasConflicts`. A missing, non-integer, or nonzero value makes the
operation fail closed. The rule applies even when the caller did not request a
separate zero-findings convenience flag.

`recoveredReadRaces` is a signed informational counter outside that required
set. It records a file that changed on the first read but was stable on the one
permitted reread. A second change is recorded in the required `readRaces` and
`incompleteScans` counters and fails closed. Scope and local-artifact bindings
are described in [Neutrality scanning](../reference/neutrality.md).

The `agent-neutrality-report.v1` contract is additive: consumers must ignore
unknown fields while continuing to require every documented completeness
counter. Release scans assume a quiescent Git worktree and index, as provided
by CI. Explicit local-artifact scans fail closed when a declared root is absent
or when the policy limits `maxLocalArtifactFiles` or `maxLocalArtifactBytes`
are exceeded.
