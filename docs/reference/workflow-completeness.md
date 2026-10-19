# Workflow completeness

Release 2.17 extends the existing workflow state, event log and checkpoint
mechanism. These local guarantees do not attest the host or measure every
model call. Unknown host usage remains unavailable rather than zero.

## Serialized mutations and reader limits

Workflow mutations take an OS process lock before loading state. The lock
covers revision and operation-ID checks through commit. Competing writers
must use their observed `--expected-revision`; the losing writer cannot
silently reuse a revision. Empty private lock files live under
`~/.agent-lifecycle-kit/workflow-locks/` for the current user profile. Their names
hash the canonical state path; case and Unicode aliases share a lock. They stay
outside project outputs and source snapshots. They remain after release and are
never stolen on the basis of age. A surviving lock file is not a held lock.
Lock acquisition is bounded; release happens on normal exit or process death.

The kernel prepares the complete next state, operation record, event and
checkpoint metadata before writing artifacts or checkpoints. JSON must fit
the existing 1,048,576-byte reader and nesting limit of 128. Rejection reports
`json-input-too-large` or `json-input-depth-exceeded` and preserves readable
state and history. This does not truncate an operation ledger or reset usage.

The event append precedes state replacement. A crash can leave the event log
ahead of state; subsequent mutation reports `workflow-split-brain` instead of
guessing a successful commit. Duplicate or unordered event revisions and
reused event operation IDs are invalid.
Legacy rows without schema/operation metadata remain readable; ID uniqueness
is checked wherever an ID is present. Missing historical metadata is not proof
of complete accounting. A multi-file commit is not a database
transaction with rollback: failures after preflight can leave immutable
evidence. Preserve it for recovery; do not delete events or recycle IDs.

## Unfinished items

`INCOMPLETE`, `BLOCKED`, `NOT_STARTED` and `DEFERRED` item outcomes belong to
non-accepting results. They cannot produce task acceptance. Keep each
`plannedItemId` stable across attempts. A later result must include every
previously unfinished item; omission reports
`task-result-unresolved-item-omitted`.

Resolving an unfinished item as `COMPLETE` requires evidence from passing
commands selected in the current result. Otherwise ALK reports
`task-result-item-resolution-unproven`. Prior attempt artifacts stay immutable.
Scope changes use the existing independently reviewed plan-change and adoption
path. A worker cannot authorize exclusion by deleting or renaming an item.
Results archived by adoption in `priorSnapshots` are checked too. To exclude
unfinished IDs, the archived independent `CONTRACT_CHANGE` review must explicitly
list `contractChangeRequest.excludedPlannedItemIds`; the recorded native request
must match that immutable review and a newer plan must actually be adopted.
Ordinary adoption or a worker's own request does not authorize omission.

## Explicit prerequisite acceptance

`dependsOn` describes package dependencies. It does not prove that another
package was accepted or published. To require offline acceptance evidence,
declare this closed extension:

```json
{
  "extensions": {
    "prerequisiteAcceptance": {
      "required": true,
      "dependencies": [{
        "packageId": "predecessor",
        "sourceRevision": "0123456789012345678901234567890123456789",
        "evidencePath": "evidence/predecessor-acceptance.json",
        "sha256": "<sha256 of the exact evidence file bytes>"
      }]
    }
  }
}
```

Required evidence must cover the declared packages, match source identity and
exact file hash, and contain independent `ACCEPTED` review evidence. Supplied
entries are validated even when `required` is false. Empty standalone packages
remain valid. `prerequisite-acceptance-*` errors block adoption; they do not
trigger a download or create missing evidence. Acceptance evidence alone does
not establish release publication or host attestation.

## Technical review interruption

A missing or truncated response is a technical interruption, not an
independent `REWORK` verdict. For an already committed result awaiting review,
use the existing run blocker:

```sh
agent-lifecycle workflow block --state run.state.json --operation-id review-wait \
  --expected-revision 12 --blocker-code review-response-missing \
  --review-task WS-01 --reason 'Review response was not delivered'
agent-lifecycle workflow resolve --state run.state.json --operation-id review-resume \
  --expected-revision 13 --reason 'Resume review of the same result'
```

`review-response-truncated` is the other supported technical code. ALK binds
the blocker to the task, attempt, result, packet, plan, source, open findings,
budgets and original deadlines. Recovery requires current authority, remaining
declared capacity, unchanged subject and unexpired absolute clocks. Accrued
usage may increase but cannot decrease or lose its history. Recovery keeps the
same attempt and does not invent a review artifact or erase a semantic finding.
`review-interruption-*` and `review-recovery-*` errors explain refusal.

This route does not schedule a provider request, grant another attempt, enlarge
a budget, reset a deadline or implement provider retry policy. Existing external
action receipts remain the route for separately required external actions.

## Architecture targets and existing packages

File and function targets emit explicit warnings; hard file, function and
top-level-symbol limits remain blocking. Function target diagnostics use
`architecture-function-target-exceeded`. The declared-limit validator checks
the report's classifications and diagnostics, not fresh source bytes; its
success cannot promote a failing architecture report.

Valid 2.16 state/history remains inspectable. New executable plans require an
explicit supported tier and its complete integrity inputs. Fix incomplete plan
inputs and obtain the required review/freeze; do not downgrade tiers or edit
frozen authority merely to pass. Version-3 state uses the existing migration
command before version-4-only technical recovery.
