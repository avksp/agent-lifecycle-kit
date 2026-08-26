# Plan review

Status: `READY_TO_FREEZE / FROZEN AFTER EXACT-DIGEST REVIEW`.

## Closed decisions

- no reviewer-provided command receives execution authority;
- `maxPlanReviewRounds` accepts only non-boolean integers from 1 through 10;
- round exhaustion escalates or blocks when an open MEDIUM, HIGH, CRITICAL or BLOCKER remains without a matching REJECTED false-positive disposition;
- `planning/manifest_contract.py` validates the bound and `review_mesh/synthesis.py` enforces terminal round receipts before emitting an outcome;
- the round policy applies to plan/Review Mesh synthesis; ordinary task acceptance retains `maxTaskAttempts: 3` in both orchestration and budget policy;
- one canonical set (`BLOCKER`, `CRITICAL`, `HIGH`, `MEDIUM`) replaces every current incomplete Medium-or-higher literal in review, implementation-audit, completion, finalization and package acceptance gates;
- only a schema-valid `agent-review-verdict.v1` bound to a complete, blocking-eligible successful `agent-external-job-result.v1` with job verdict `PASS` or `FAIL` counts as reviewer participation;
- no-verdict resource use remains visible without acceptance effect;
- findings-only Review Mesh import remains advisory and does not count as participation;
- reviewer agreement and synthesis `PASS` do not close a finding; immutable dispositions remain the only classification authority;
- provenance requirements apply to statistical/error-rate claims, not every artifact;
- duplicate sample identities do not increase effective sample count, and stale source revision/lineage fails closed;
- quality floors and no-auto-apply behavior remain unchanged.
- the accepted Release 2.6 versions of `metrics_parser.py`, `dispatch_observability.py`, `contracts/schemas.py` and `metrics/__init__.py` are mandatory rebase inputs; this release extends rather than replaces them.
- the executable base is accepted Release 2.6 merge `30e2f2a55a2b8d959fa22b884e122952a2711ff7`; prior revision-4 audit evidence is historical and cannot freeze this package.
- the observed Release 2.6 accounting values are frozen in `baseline-2-6.md`; one baseline validates metric semantics but cannot justify an optimization percentage.

## Independent review focus

1. command-injection boundary between reviewer text and approved check profile;
2. round policy cannot turn budget pressure into acceptance;
3. actual versus intended reviewer participation;
4. independent source and sample adequacy mathematics;
5. replay and conflicting disposition handling;
6. accounting compatibility with Release 2.6.
7. publication ownership includes both install-and-first-run guides required by the publication contract.

## Revision 6 remediation

Independent GLM 5.3 and Grok 4.6 xhigh audits both returned `CHANGES_REQUIRED` at revision 6 and digest `a034763b95da63f79e4ef5a7e30f297c6b11576bc773205e5edfee69be096774`. Revision 7 addresses every blocking finding:

- adds the two publication-pin guides to WS27-03;
- defines blocking open severity across all synthesis buckets and preserves REJECTED as the only false-positive exception;
- closes the live CRITICAL omission in all three existing review gates;
- binds participation to existing review-verdict and external-job contracts without adding a second authority path;
- makes duplicate identity and stale lineage fail closed for statistical evidence;
- moves schema registration and audit-optimization ownership to WS27-02;
- adds existing Review Mesh CLI and verdict regression tests plus operator documentation to the write set.

The revision 6 verdicts are historical remediation evidence. They cannot freeze revision 7; both independent auditors must re-audit the new digest.

## Revision 7 remediation

Independent GLM 5.3 and Grok 4.6 xhigh audits both returned `CHANGES_REQUIRED` at revision 7 and digest `42d3ac6856dbb4fcda5241a9d6dd2453b9f73f9d90bc637192b01080814fe84e`.

- GLM reproduced the same CRITICAL fail-open in implementation-audit, completion and finalization paths outside the revision 7 write set. Revision 8 adds every current acceptance filter with the incomplete Medium-or-higher literal, its direct regression tests and a dedicated `AC27-SEVERITY`/`EV27-SEVERITY` contract.
- Grok found that revision 7 excluded a valid `SUCCEEDED + verdict=FAIL` external job from reviewer participation. Revision 8 counts both `PASS` and `FAIL` for complete blocking-eligible successful jobs; failed/incomplete jobs and `NO_FINAL_VERDICT` remain non-participating.

The revision 7 verdicts are historical remediation evidence. They cannot freeze revision 8; both independent auditors must re-audit the new digest.

## Freeze conditions

- rebase on accepted Release 2.6: complete;
- pass structural gates and fresh independent S2 audits from GLM 5.3 and Grok 4.6 xhigh: complete for revision 8;
- close every Medium/High finding: complete, with only non-blocking Low/Info residuals;
- bind the final FROZEN manifest digest to `plan-review-r8.json` and generate the v2 lock: required before implementation starts.
