# Developer overview

Release 2.7 composes the finding-check lifecycle from 1.86, external checks from 1.88, bounded external jobs from 2.5 and accounting from 2.6.

Reviewer text is untrusted. A `reproduction` field may explain a proposal but cannot define argv, executable, environment or filesystem authority. Execution requires a frozen check identity and an approved profile already covered by ALK's shell-free process boundary.

Round budgets are stop/escalation controls, not quality downgrades. `maxPlanReviewRounds` is a non-boolean integer from 1 through 10. Participation composes the existing contracts: a schema-valid `agent-review-verdict.v1` plus a matching complete, blocking-eligible `agent-external-job-result.v1` from a successful terminal job with job verdict `PASS` or `FAIL`. A successful reviewer job that reports `REWORK` is still a participating voice. Provider close, timeout, interrupted children, findings-only imports, malformed output and no final verdict remain visible resource use with no participation or acceptance effect.

Review agreement is not remediation. All findings from the synthesis buckets are joined to immutable terminal dispositions. An open `MEDIUM`, `HIGH`, `CRITICAL` or `BLOCKER` remains blocking unless a matching disposition rejects it as a false positive. Release 2.7 replaces the duplicated incomplete gate literals with one canonical blocking-severity set consumed by the existing review, implementation-audit, completion, finalization and plan-package paths.

Statistical evidence gets an explicit provenance envelope. For a zero-observed-error claim with one-sided 95% bound, the default rule-of-three requires `n >= ceil(3 / threshold)`; a different method must be declared and independently checked. Only unique samples at the expected source revision/lineage count, and implementation-derived samples cannot be relabelled as independent holdout data.

The accepted Release 2.6 accounting is the observed baseline for metric semantics. Its audit values are measured, implementation/controller tokens are unavailable, and the remaining phase times are time windows. Release 2.7 must preserve those distinctions in a tracked fixture and must not derive an optimization percentage from one release.
