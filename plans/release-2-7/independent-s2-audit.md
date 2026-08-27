# Independent S2 audit history

## Revision 6

- Base: `main @ 30e2f2a55a2b8d959fa22b884e122952a2711ff7`
- Plan revision: `6`
- Plan digest: `a034763b95da63f79e4ef5a7e30f297c6b11576bc773205e5edfee69be096774`
- GLM 5.3 verdict: `CHANGES_REQUIRED`
- Grok 4.6 xhigh verdict: `CHANGES_REQUIRED`

Both auditors independently reproduced the unsafe Review Mesh shape where two reviewers agreeing on an open `MEDIUM`, `HIGH` or `CRITICAL` finding produced synthesis `PASS` with the finding under `acceptedFindings`. Both also reproduced the omission of `CRITICAL` from the existing workflow, independent-review and structured-verdict open-finding gates.

Additional blocking findings covered publication-pin ownership, schema/workstream sequencing, explicit composition with existing review-verdict and external-job contracts, and duplicate/stale statistical samples. Revision 7 remediates these findings in the plan package and requires a fresh audit against its exact digest before freeze.

Raw model transcripts remain under `work/release-2-7/s2/` and are not plan authority.

## Current status

## Revision 7

- Base: `main @ 30e2f2a55a2b8d959fa22b884e122952a2711ff7`
- Plan revision: `7`
- Plan digest: `42d3ac6856dbb4fcda5241a9d6dd2453b9f73f9d90bc637192b01080814fe84e`
- GLM 5.3 verdict: `CHANGES_REQUIRED`
- Grok 4.6 xhigh verdict: `CHANGES_REQUIRED`

GLM reproduced additional CRITICAL fail-open paths in implementation-audit, completion and finalization gates outside the revision 7 write set. Grok confirmed the revision 6 remediation but found that `SUCCEEDED + verdict=FAIL` was incorrectly excluded from reviewer participation even though the existing external-job contract makes that a complete blocking-eligible result.

Revision 8 replaces all current incomplete Medium-or-higher gate literals with one canonical blocking-severity set and counts complete blocking-eligible successful external jobs with either `PASS` or `FAIL` verdicts.

## Revision 8

- Base: `main @ 30e2f2a55a2b8d959fa22b884e122952a2711ff7`
- Plan revision: `8`
- DRAFT plan digest audited semantically: `6bcb5d2156a2ac8248cabc04ccd9f4f2c77744ea2fdd8ab628019fd7d99944fd`
- GLM 5.3 verdict: `ACCEPTED`, explicitly equivalent to `READY_TO_FREEZE`
- Grok 4.6 xhigh verdict: `READY_TO_FREEZE`
- Open Medium/High/Critical findings: `0`

Both auditors reproduced the revision 6 and 7 defects against the Release 2.6 base and verified that revision 8 supplies concrete owners, direct tests and deterministic evidence for every blocker. Grok returned no findings. GLM returned two non-blocking Low findings about display-only CRITICAL sorting and naming the source-scan host test, plus an informational route-grammar hardening opportunity. The source scan will live in `tests/contracts/test_review_verdict.py`; display ordering and route grammar may be tightened within already owned files without changing acceptance authority.

The final canonical review binds the same revision 8 semantics plus FROZEN metadata and declared review/audit files to the exact final manifest digest. Raw model transcripts remain under `work/release-2-7/s2/`.

## Current status

Revision 8 received independent S2 approval, an exact-digest review and a verified v2 lock. Its implementation reached final audit, where `AUDIT-WS27-03-F1` triggered the revision 9 contract-change route. Revision 8 authority is therefore historical and cannot authorize the revised package.

## Revision 9

- Trigger: final-audit finding `AUDIT-WS27-03-F1`
- Status: `AWAITING_FRESH_INDEPENDENT_S2_AUDIT`
- Scope: distinct current/comparison identity plus non-overlapping remediation ownership and downstream metrics revalidation

Revision 8 review and lock do not authorize this contract change. Revision 9 requires a fresh read-only independent audit, exact-digest `READY_TO_FREEZE` review and a new v2 lock.

### Audit round 1

- Route: OpenCode `zai-coding-plan/glm-5.3`, strict read-only permissions
- DRAFT digest: `99de06b93cf107b57a6d1e75243e58158ce3930789990096c5d0cc4b3910d231`
- Verdict: `CHANGES_REQUIRED`
- Open Medium: `F1`, under-specified label-independent identity

The audit confirmed revision 8's duplicate-comparison defect and accepted the ownership/DAG/compatibility design. It found that `inputDigest` includes `releaseId`, so a release-label-only mutation changes both originally declared axes. Revision 9 now defines a separate content digest over the canonical input excluding `releaseId` and `inputDigest`, requires pairwise-unique source revision and lineage, and names the fail-closed blocker. A fresh audit is required against the new digest.

### Audit round 2

- Route: fresh OpenCode `zai-coding-plan/glm-5.3` session, strict read-only permissions
- DRAFT digest: `5def6a9b3ae70ee42664ab7a2501e0e2ac9a36bffeb5a75a0f2dcb8f12a7f70e`
- Verdict: `READY_TO_FREEZE`
- Open Medium/High/Critical/Blocker: `0`

The audit reproduced the original defect, verified all four identity axes, the constructible mutation matrix, non-overlapping ownership, the `WS27-01 -> WS27-04 -> WS27-02 -> WS27-03` DAG, and the exact-compatible preservation rule. Two Low wording inconsistencies were corrected before the FROZEN candidate. An exact-digest review is still required because those corrections and FROZEN metadata changed the manifest/package after the DRAFT verdict.
