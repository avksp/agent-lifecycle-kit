# Developer overview

Release 2.5 is activated for bounded external tool jobs after the accepted 2.4.1 correctness patch.

The feature composes existing ALK state and evidence. It does not create a second workflow authority, provider runtime, background service or mandatory artifact for ordinary tasks. `activation-evidence.md` records two concrete failures that the synchronous external-check receipt cannot represent.

Each attempt owns an immutable artifact namespace. Cancellation must terminate the declared process group, reject later writes and produce a terminal receipt. A timeout, provider close, interrupted child audit or missing consolidated verdict is not success and has no acceptance effect.

The job service composes the existing `run_process` and `ProcessGroupOwner` APIs. Their shared implementation stays read-only in this release; the existing cleanup and shell-free boundary tests run as regression gates. If implementation proves that those APIs are insufficient, the plan must be reopened instead of widening WS25-02 implicitly.

## Dependency rule

Contracts remain standard-library-only and authority-free. Optional host behavior stays behind adapter boundaries. Views and imported results remain untrusted until checked by the authoritative workflow.

## Freeze rule

The frozen `baseRevision.sha` is the accepted 2.4.1 merge. Revision 10 closes the independent S2 findings and binds the executable plan review before lock generation.
