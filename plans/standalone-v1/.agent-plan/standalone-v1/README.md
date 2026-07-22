# Agent Lifecycle Kit standalone release

Authored phase: `SPECIFICATION_CANDIDATE_R06_PLAN_CANDIDATE_R06`

Authoritative runtime status is stored in `../../plan.manifest.json`.

Plan revision: `6`

## Reading Order

1. `product-specification-r06.json`
2. `00-developer-overview.md`
3. `01-source-preflight.md`
4. `02-architecture-contracts.md`
5. `03-workstreams.md`
6. `04-agent-dag-and-ownership.md`
7. `05-worker-prompts.md`
8. `06-validation-and-evidence.md`
9. `07-acceptance-and-lead-checklist.md`
10. `08-plan-review-and-change-control.md`
11. `09-product-resource-budgets.md`
12. `10-release-matrix.md`
13. `11-adapter-compatibility-and-maturity.md`
14. `12-authority-and-environment-profiles.md`
15. `13-modular-controller-architecture-r06.md`
16. `agent-lifecycle-budget-profile.v1.json`
17. `adapter-contract-inventory-r02.json`
18. `ci-matrix-profile.v2.json`
19. `benchmark-authority-profile.v1.json`
20. `neutrality-authority-profile.v3.json`
21. `release-assembly-profile.v1.json`
22. `final-proof-authority-profile.v2.json`
23. `reviews/specification-review-r05.json`
24. `reviews/plan-review-r04.json`
25. `reviews/plan-review-r01-subject-disclosure.json`
26. `../../plan.manifest.json`

## Launch Gates

- Resolve blocking questions and fill every authoritative plan file.
- Select the smallest sufficient SDD tier; freeze and independently review an
  external S2 specification before plan review.
- Pass deterministic ready-profile validation.
- Obtain an independent full `READY_TO_FREEZE` review for this revision.
- Freeze through the lock generator; never hand-edit status to `FROZEN`.
- Obtain execution authorization when start mode requires it.
- Supply the external neutrality authority/trust environment and pass the
  signed controller gate before every downstream launch and after each attempt.
- Accept every task independently and pass the final implementation audit.

## Current Gate

Specification revision 3 remains immutable prior authority. Plan review r04
first exposed three proof-contract gaps. Specification revision 4 attempted to
close them, but independent specification review r05 rejected that subject
with open `SPEC-005` through `SPEC-008`: output publication was not fully
write-once, the external authority contract drifted, release identities were
ambiguous and terminal completion still had a self-reference/cycle.

Specification revision 6 and plan revision 6 are `REOPENED` candidates. They
preserve the r05 neutrality, release assembly and final-proof corrections, add
Hermes as a required offline `EXPERIMENTAL` adapter surface and require the
controller implementation to be modular rather than a monolithic production
`workflowctl.py`. Specification r06 still requires a new independent review
and specification freeze; plan r06 then requires a full independent review and
plan refreeze. No implementation task may resume before both gates pass and a
new lock is generated.
