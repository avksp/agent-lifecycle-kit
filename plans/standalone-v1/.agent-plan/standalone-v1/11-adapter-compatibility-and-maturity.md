# Adapter Compatibility And Maturity

## Required Offline Baseline

Each of the five adapter workstreams is executable with network denied and no
installed live surface. It must produce an installable adapter bundle and pass
synthetic install, discovery, envelope, capability, unsupported-operation,
cancellation, result, review and usage-attestation conformance.

The required release maturity is `EXPERIMENTAL`. Absence of a live surface is
not a blocker and consumes no retry. It only prevents promotion to `VERIFIED`.

The canonical immutable normalized contract inventory for specification r06 is
`adapter-contract-inventory-r02.json`.
`12-authority-and-environment-profiles.md` is explanatory only. Any mismatch
between the JSON authority and prose is a freeze and execution blocker. Adapter
tasks consume the JSON as local plan context and never discover or choose an
authority source at runtime.

The first release surfaces are Codex, Claude Code, Cursor, Hermes and
OpenCode. Hermes is treated the same way as the other surfaces: the required
release target is offline `EXPERIMENTAL`, while live `VERIFIED` status requires
separate Hermes-owned receipts. Hermes skill installation/discovery uses the
Hermes skills system and external skill directory mechanism; lifecycle
semantics still remain in the shared core.

## Compatibility Descriptor

Every adapter bundle contains one validated descriptor with:

- kit host-protocol version `agent-lifecycle-host.v1`;
- adapter package-format version;
- authoritative host contract id and content SHA-256;
- official source URI or host-distributed schema identity;
- retrieval timestamp and retrieval tool version;
- closed minimum and maximum offline contract revisions;
- optional minimum and maximum live-tested host versions;
- operation capability matrix and unsupported-operation error code;
- maturity, synthetic evidence digest and optional live evidence digest;
- source license/redistribution classification.

Unbounded values such as `latest`, an absent maximum contract revision, an
unhashed source, or a self-authored compatibility claim fail validation. At
`EXPERIMENTAL`, the live-tested host range must be absent and no live support
claim is allowed. At `VERIFIED`, both live-tested bounds are required and must
be covered by fresh live receipts. The authoritative normalized snapshot must
be license-compatible, contain no credentials or origin-specific information
and stay within its adapter root.

## Optional Live Promotion

Live promotion is outside the required implementation DAG and requires
explicit host authority. `VERIFIED` needs fresh host-owned receipts for
install, discovery, launch, wait, cancel, resume, tool execution, result
collection, usage attestation, task audit and final audit across the declared
live-tested host range. Missing capability, stale evidence or a version
outside that range keeps the adapter `EXPERIMENTAL`; no fallback may raise
maturity.
