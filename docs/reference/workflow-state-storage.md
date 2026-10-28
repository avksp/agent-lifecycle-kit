# Workflow state storage and recovery

New workflow initialization remains `agent-workflow-state.v4`. The candidate
2.30 runtime supports inline v4 and explicit compact `agent-workflow-state.v5`.
Migration changes storage representation, not execution authority. Use a qualified
runtime that supports v5 for every subsequent authority read or mutation; 2.27
and 2.29 native loaders refuse that schema. There is no automatic downgrade.

## Representation and bounds

The compact state retains current tasks, bounded attempt history, budgets,
authorization and the append-only operation ledger. Immutable ownership receipts,
result change-set evidence and complete prior plan snapshots are stored as
canonical JSON objects under the state's adjacent `.storage/objects/` directory.
Equal canonical bodies share one object. References use
`agent-workflow-storage-reference.v1` with kind, SHA-256, bytes, path, lineage
and item counts. SHA-256 covers canonical JSON without LF; `bytes` includes its
single final LF. Historical evidence keeps its original plan/task/attempt lineage.
Snapshots retain `HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING`.

| Bound | Limit |
| --- | --- |
| Each authority JSON, including root and each leaf | 1,048,576 bytes |
| Current tasks / archived plan snapshots / operation-ledger entries | 32 / 128 / 2,048 |
| Distinct reachable objects / complete reachable bytes | 4,096 / 64 MiB |
| Cumulative distinct objects/bytes validated in one operation | 4,096 / 64 MiB |
| Retained storage, including unreachable retry objects | 128 MiB |
| Reference depth | State → snapshot → leaf, at most two edges |
| Cooperative storage I/O deadline | 30 seconds for one operation |

These count limits do not promise every combination of large metadata will fit.
Residual inline metadata must still fit the root limit. A single oversized leaf
refuses; this version does not split arbitrary objects. Warnings begin at 75%
of root/count/byte ceilings. Capacity refusals report category, current, required,
limit and the migration/replanning route. No history, costs, operation IDs or
UNKNOWN holds are removed to make room. Unreachable immutable objects remain
retained; no garbage-collection command is introduced.

Every authority read and mutation validates the complete reachable graph,
including old snapshots unrelated to the selected task. Missing, malformed,
noncanonical or changed bytes and incorrect kind, hash, length, lineage or counts
refuse. Cycles, nested snapshots, aliased paths, traversal, symlinks and Windows
reparse paths are unsupported. A bounded operation context shares verified raw
bytes and the original deadline; it confers no trust on a later operation.
The deadline is checked around I/O and cannot interrupt a blocked OS syscall.

## Explicit migration

Retain the complete state, event log, referenced artifacts and source identities
before proceeding. Use the exact current state/source revisions and a unique
operation ID, for example:

```sh
agent-lifecycle workflow state-migrate \
  --state work/run/state.json \
  --target-schema agent-workflow-state.v5 \
  --expected-revision 64 --source-revision <source-sha> \
  --operation-id migrate-storage-64
```

Migration may run on a blocked run with expired authorization. It creates and
verifies an immutable adjacent `state.json.v4-backup-<raw-sha>.json`, prepares
sidecars, and records one actual revision/operation/event and a migration receipt.
The receipt binds original raw bytes/hash, source and target revisions and storage
root. The existing event log is append-only. Phase, blockers, grants and their
expiry/revocation, run/attempt clocks, failed attempts, budgets, costs, UNKNOWN
and accepted artifact identities remain unchanged. Migration neither resumes
nor accepts a task. Repeated migration does not add another event or charge.

When state is outside an already ignored work directory, configure ordinary Git
exclusions for the complete authority footprint before native task snapshots.
For root-level `state.json` and `events.jsonl`, the relevant entries are:

```gitignore
/state.json
/state.json.storage/
/state.json.v4-backup-*.json
/events.jsonl
```

Also exclude the project's declared runtime artifact directory as appropriate.
Use the actual state/event names and directories; ignoring only the root state
does not exclude sidecars or backups. This is ordinary Git configuration. It does
not weaken ownership checks for unrelated source paths or provide host enforcement.

## Failures and recovery

Pure preparation and prospective root/event/checkpoint/sidecar preflight occur
before publication. Existing private, contained, no-replace authority I/O writes
objects before publishing references. Verified same-byte orphans are reusable on
retry; different bytes at an existing digest path refuse. Observers and policy
checks receive exact prepared sidecar and backup writes.

A failure before publication leaves state/events unchanged. A later failure can
leave immutable objects or a checkpoint, an appended event without replaced
state, or an already committed state. Retain the actual partial outcome and
receipt. Event/state divergence requires the existing split-brain recovery route;
an error response alone cannot prove either rollback or task acceptance. Writers
remain serialized by the existing transaction lock and stale revision guards;
there is no broader parallel-writer guarantee.

Keep the qualified v5 runtime and diagnose the named missing/corrupt object or
capacity gate. Do not edit references, signed artifacts, grants, ledger entries
or clocks by hand. Restore a pre-migration snapshot only in a disposable isolated
replica after preserving failed/post-migration evidence. The immutable v4 backup
is evidence, not permission to rewind a live run. Live in-place rollback and
downgrade are unsupported.

## Separate authorization renewal

`workflow authorization-renew --receipt <fresh-receipt>` is a separate, explicit
same-run transition with the ordinary state/source/revision/operation guards.
Its typed `agent-workflow-authorization-renewal-receipt.v1` binds the predecessor
grant, current lineage, unchanged budgets, original clocks and task/artifact
identities. Only the authorization expiry advances. A digest is declared user
authority within the existing trust boundary, not a new signature.

The eligible phases are RUNNING with an existing VERIFYING task and committed
result, or FINAL_AUDIT with every required task accepted. BLOCKED/technical
recovery, closingWindow, revoked/ungranted, plan-only, terminal and unsupported
legacy grants refuse. Renewal does not resume, start, retry or accept work, change
budgets or renew run/attempt deadlines. Ordinary acceptance still checks all
evidence; it can canonically clear active attempt-clock fields afterwards while
historical evidence retains their original values. Existing unsupported-host and
DECLARED-ledger restrictions remain.

Portable fixture actors are explicitly synthetic. Component scale proof, native
fixture proof, isolated application rehearsal and live acceptance have different
scope. The isolated RMK rehearsal migrates exact historical incident64 and checks
expired-authorization refusal only. It does not renew a live grant, accept GUARDS
or close the RMK incident. Live recovery requires current project-owned review,
path/source reconciliation and explicit authorization after qualified delivery.
