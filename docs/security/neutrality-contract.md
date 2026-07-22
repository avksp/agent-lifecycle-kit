# Neutrality Authority Contract

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
