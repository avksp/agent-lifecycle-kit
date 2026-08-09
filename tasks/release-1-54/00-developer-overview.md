# Developer overview

## User outcome

Usage reports clearly distinguish evidence reported by a host from an estimate.
Users can trust S1/S2 gates not to treat a text-size estimate as a billed token
count.

## Architecture boundary

The core owns the canonical receipt validator, aggregation and conservative
fallback classification. Adapter directories own parsing of their host's
exported stream, usage file or result artifact.

The existing parsers in `tools/live_hosts` are migration inputs, not a second
authority. After this release each reference runner and harness calls the same
adapter-local normalizer. The portable descriptor validator checks only the
declarative normalizer status and path; it does not interpret a host payload.

Each descriptor may declare `usageNormalization` with contract
`adapter-local-usage-normalizer.v1`, status `UNSUPPORTED`, `FIXTURE_ONLY` or
`QUALIFIED`, a repository-relative normalizer path, host artifact format and
maximum artifact size. `QUALIFIED` additionally requires non-empty
qualification evidence, a qualified host range and `acceptedForS1S2: true`;
the other statuses require `acceptedForS1S2: false`. A missing block is treated
as unsupported.

The adapter normalizer parses only allowlisted numeric/session fields and
returns a canonical `agent-lifecycle-model-usage-receipt.v1` sidecar. The
sidecar binds operation id, route digest, adapter/host, model class and hash,
plus source SHA-256, byte count, format and normalizer digest. The existing
`agent-host-operation-receipt.v1` remains unchanged and cannot authorize a risk
gate by itself.

## Risk level

SDD tier: `S2`.

Reasons: multiple executable owners, architecture risk, security risk and
external host-output compatibility risk.

## Execution model

```text
WS64-01 -> WS64-02 -> WS64-03 -> WS64-04
```

## Safety

- An adapter normalizer accepts only a declared, bounded host artifact format.
- Raw host output is never copied to a portable receipt; parsers extract only
  allowlisted fields and retain a path-free digest/size identity.
- `ESTIMATED` values are conservative and never satisfy S1/S2 attestation.
- Attestation requires both `source: host` and `status: ATTESTED`; aggregation
  cannot infer either value from token counters alone.

## Review focus

- Check that host-specific parsing stays outside `src/agent_lifecycle` core.
- Check reuse of `agent-lifecycle-model-usage-receipt.v1`.
- Check exactness is not claimed for adapters that have no live evidence.
- Check runner and harness paths cannot drift into duplicate host parsers.
- Check descriptor validation distinguishes `FIXTURE_ONLY` from live-qualified
  usage without importing an adapter implementation into core.
- Check the model-usage sidecar carries all route and source bindings while the
  host-operation receipt remains backward compatible.
