# Runner Recovery Receipts

Runner recovery receipts are optional evidence for long-running or multi-attempt
work. They do not replace workflow state; they record what happened around an
attempt so a later reviewer can distinguish normal retry, restore, abandon and
selected-attempt decisions.

## Attempt Snapshots

`agent-runner-attempt-snapshot-receipt.v1` records one recovery action:

- `snapshot`: stores a digest-bound runner or attempt snapshot.
- `restore`: points to the snapshot digest used as restore source.
- `abandon`: records why an attempt is no longer selected.
- `select`: records the attempt and digest selected as the surviving result.

Validation recomputes the snapshot and receipt digests, checks lineage, and
fails if a restore or selected attempt is claimed without the required digest.

## Worker Leases

`agent-worker-lease-receipt.v1` records worker lease and heartbeat state. The
receipt classifies the lease as:

- `active` when `observedAt` is not later than `expiresAt`;
- `expired` when `observedAt` is later than `expiresAt`;
- `completed` when `completedAt` is present.

The classification is deterministic from timestamps and is rechecked during
validation. This keeps recovery metadata narrow; it is not a second scheduler.

## Phase Resources

`agent-phase-resource-measurement.v1` records phase-level tokens, duration and
resource counters using the Release 1.8 usage-export entry envelope. Phase
measurements are token/resource based and reject monetary fields such as
`cost_usd`; host-reported money remains outside this phase receipt.

The receipt includes an embedded `agent-usage-export.v1` object so existing
usage export totals and redaction checks can be reused.

## Fresh Context Recipe

Fresh-context recovery is recipe/evidence only. A controller may record that a
worker resumed from a compact handoff, diagnostic bundle, status view, event
feed or progress view, but that record does not replace workflow state and does
not mutate lifecycle state by default.

Use fresh-context evidence when an attempt was restarted in a new host session
or a small model needed a compact reconstruction. The evidence should point to
the source artifacts and their digests; the reviewed plan and workflow state
remain authoritative.
