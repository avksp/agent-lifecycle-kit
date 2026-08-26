# Plan review

Status: `REVISION 6 FINAL BYTES / INDEPENDENT S2 ACCEPTED / LOCK PENDING`.

## Closed decisions

- CLI commands expose existing APIs and do not auto-approve or auto-authorize;
- lock creation requires a digest-bound independent review, not only a `FROZEN` status string;
- lock output is the canonical package lock path and uses no-replace semantics;
- the final manifest pre-declares the review path before review; exact current-manifest digest binding uses no normalization;
- review binding is implemented inside WS26-01-owned `freeze/package_integrity.py`, leaving `review/validation.py` read-only;
- phase and accounting source artifacts are explicit and bounded;
- release accounting has an operator CLI route, not only a Python API;
- missing telemetry is unavailable, never zero;
- parallel compute and elapsed wall remain different dimensions;
- existing checkpoint/handoff primitives are reused;
- no target ratio can lower a required gate;
- optimization targets after 2.6 must be derived from comparable post-2.6 evidence rather than arbitrary percentages;
- the accepted Release 2.5 schemas, CLI and publication surfaces are mandatory rebase inputs;
- both install guides required by the 2.6.0 package-pin gates belong to WS26-03;
- the phase-count limit is exactly 256, the lock CLI uses a dedicated helper, and handoff evidence names its tracked continuity test.

## Independent review focus

1. lock creation cannot become self-freeze or write outside the canonical lock path;
2. review package/revision/digest binding, no-replace and package inventory behavior;
3. accounting additivity, availability and confidence semantics;
4. release-accounting CLI/API equivalence and output bounds;
5. phase measurement compatibility with existing v1 artifacts;
6. plugin/core version mismatch reporting;
7. absence of a second workflow or context authority;
8. direct existing regressions remain in the owning workstreams and the complete suite is mandatory.

## Freeze sequence

1. Keep these revision-6 manifest bytes unchanged: accepted 2.5 base, `status: FROZEN`, `planReview.report` and `plan-review-r6.json` already declared.
2. Obtain fresh independent S2 verdicts over revision 6 and close every Medium/High finding. Any manifest change increments revision and repeats S2.
3. Write the machine-readable accepted review to the pre-declared `plan-review-r6.json`; require its `reviewedPlanHash` to equal the unchanged revision-6 manifest digest.
4. Update narrative S2 chronology only; it is inventory-bound by the later lock but does not alter manifest bytes.
5. Pass structural, review-binding and package checks, then generate the v2 lock last.
