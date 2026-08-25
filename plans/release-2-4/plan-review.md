# Plan review

Status: `FROZEN / IMPLEMENTATION READY (REVISION 9)`.

## Closed decisions

- the feature is optional and inactive by default
- existing workflow state remains the only authority
- no provider, network or external-tool runtime enters the core
- ordinary runs create no new work or artifact when the feature is unused
- the bounded activation case is recorded in `activation-evidence.md`
- the canonical plan package is Git-visible under `plans/release-2-4/`; only
  generated runtime evidence remains under ignored `work/`
- the release number is fixed at `2.4.0` and the plan base is the accepted 2.3 merge
- high-severity acceptance must pass through the existing authoritative
  implementation-audit/Review Mesh boundary, not only a Bug Forensics receipt
- the manifest-to-task propagation of the security implementation-audit policy
  is an explicit contract, and the policy is enforced by `accept_task`
- the existing CLI routing surfaces (`parsers.py` and
  `dispatch_contracts.py`) are explicitly owned where the profile is exposed
- review evidence has declared assignment, verification, audit and acceptance
  artifact paths with machine-readable `independentEvidenceIds`
- the final implementation scope explicitly owns the runtime manifest-extension
  validator and the public audit, quality and Review Mesh export facades used by
  the security profile; these are integration surfaces, not unplanned writes

## Independent review focus

1. whether the pre-implementation activation case demonstrates a real lifecycle gap and the candidate conformance run executes every declared step
2. whether existing contracts can solve it without a new surface
3. authority, privacy, replay and resource boundaries
4. negative fixtures and unavailable behavior
5. English and Russian operational parity
6. whether active reproduction remains opt-in and bounded
7. whether the adopted task, rather than only the manifest or a helper gate,
   carries the independent-verification requirement to task acceptance

## Freeze conditions

- keep `activation-evidence.md` as a tracked pre-implementation authorization
  record and produce the separate candidate activation receipt;
- keep the entire plan package Git-visible under `plans/release-2-4/`;
- assign the next available release number and update every release-target surface;
- rebase onto the latest accepted mandatory baseline rooted at Release 2.0 and reconcile separately accepted candidates;
- raise `planRevision` after remediation;
- pass completeness, plan check, acceptance and refs checks;
- close every independent S2 Medium or High finding;
- use one authoritative `maxTaskAttempts` value (`orchestration.maxTaskAttempts`);
- generate `agent-plan-lock.v2` only for the final audited revision.

## Scope reconciliation for revision 9

During implementation, a diff-to-write-set check found four required support
surfaces that were already part of the 2.4 behavior but were omitted from the
revision-8 list: `planning/manifest_contract.py` and the public `audit`,
`quality` and `review_mesh` package facades. The scope is unchanged: these
files only validate or expose the profile contracts already defined by the
three workstreams. They are now assigned explicitly and the lock is regenerated
for revision 9 before acceptance.
