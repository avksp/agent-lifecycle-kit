# Evidence plan

## EV27-ROUNDS

Validate that `maxPlanReviewRounds` accepts non-boolean integers 1 through 10 and rejects booleans, zero, negatives and 11 or greater. Drive `review_mesh/synthesis.py` with terminal SUCCEEDED, FAILED, CANCELLED and EXPIRED job receipts plus malformed/no-final-verdict output. A reviewer voice requires both a schema-valid `agent-review-verdict.v1` and a matching complete, blocking-eligible `agent-external-job-result.v1` whose terminal state is `SUCCEEDED` and verdict is either `PASS` or `FAIL`. A `SUCCEEDED + FAIL` result with a valid `REWORK`, `CONTRACT_CHANGE` or `BLOCKED` review verdict still counts as participation. Findings-only imports, prose, transport success, process exit status, failed/incomplete jobs and `NO_FINAL_VERDICT` remain visible resource use without participation.

Exercise one reviewer with each open `MEDIUM`, `HIGH`, `CRITICAL` and `BLOCKER` finding and two reviewers agreeing on each same open finding. Flatten `acceptedFindings`, `rejectedFindings` and `unresolvedFindings`, join exactly one immutable disposition by finding ID, and assert that agreement or synthesis `PASS` never closes a finding. An open `MEDIUM+` finding remains blocking when undisposed, confirmed, unavailable or approval-required; only a matching `REJECTED` false-positive disposition is non-blocking. Exercise one clean-stop round, declining yield, budget exhaustion in both single-reviewer and agreed-open shapes, and budget exhaustion with no blocking open finding. The blocking cases return only REPLAN_REQUIRED, SPLIT_REQUIRED, OPERATOR_DECISION or BLOCKED. Deleting, duplicating or forging a round receipt or verdict binding fails closed and cannot yield ACCEPTED.

## EV27-SEVERITY

Use the canonical blocking-severity set from `contracts/review_verdict.py` in every existing gate that currently embeds `{BLOCKER, HIGH, MEDIUM}`. For each of `BLOCKER`, `CRITICAL`, `HIGH` and `MEDIUM`, inject an open finding into independent review, structured verdict, task review, implementation-audit report, final implementation audit, workflow finalization, specification completion and reviewed plan-lock/package input. Assert the accepting status fails with the gate's stable open-finding code. `LOW` and `INFO` controls remain non-blocking. Add a source scan regression proving no current Medium-or-higher acceptance filter reintroduces the incomplete literal set.

## EV27-CHECKS

Inject shell separators, output redirection, traversal, environment assignments and executable names into reviewer `reproduction` text. Assert no process starts. Bind the same finding to an approved check identity/profile and execute through the existing bounded external check/job boundary; mutate source, plan, lock and check digest independently.

## EV27-DISPOSITION

Build a batch with confirmed, reviewer-false-positive, unavailable and approval-required findings sourced from every Review Mesh synthesis bucket. Replays are idempotent; conflicting second dispositions fail; evidence digests remain immutable. An agreed open HIGH with `CONFIRMED` remains blocking, while the same immutable finding with a valid `REJECTED` false-positive disposition is non-blocking.

## EV27-PROVENANCE

Use one implementation-derived set, one independently produced holdout, one undeclared shared-source set, duplicate sample identities and a set bound to a stale source revision/lineage digest. Only unique samples with current lineage from the declared independent set can satisfy a criterion requiring source independence. Duplicate identities do not increase effective count; stale lineage fails the evidence set rather than being silently excluded. Raw sample payloads remain outside the portable receipt.

## EV27-ADEQUACY

Define effective independent count as the number of unique sample identities with current source revision/lineage that satisfy the declared producer-independence rule. Run rule-of-three boundary fixtures for 2% at n=149 and n=150, and for 1% at n=299 and n=300. Mutate threshold, confidence method, observed errors, duplicate identities, source revision, source lineage digest and effective independent count.

## EV27-METRICS

Use tracked synthetic equivalents of the Agentic, TenderCRM and Board shapes. Add a portable fixture reproducing `baseline-2-6.md` without local paths or raw transcripts. Verify tokens/time per confirmed finding, no-acceptance-effect share, rejected-finding share and post-audit-remediation share. The Release 2.6 fixture must preserve measured audit tokens/wall/compute, time-window-only process/implementation/remediation values and unavailable non-audit tokens. A mutation that substitutes zero for unavailable data or derives a percentage reduction from this single release must fail closed. Missing implementation/controller telemetry remains unavailable and blocks cross-project ratio claims.

## EV27-DISTINCT-COMPARISON

Build one complete current measurement and two complete comparison measurements whose `releaseId`, `sourceRevision`, `sourceLineageDigest` and label-independent content digest are pairwise unique. Define that digest as `canonical_digest(input - {releaseId, inputDigest})`. Preserve the existing two-release PASS behavior, then independently mutate: current artifact reused as comparison; the same bytes supplied from another path; repeated comparison artifact; repeated `releaseId` with otherwise distinct input; `releaseId` changed with only `inputDigest` recomputed; and metrics changed while `sourceRevision` or `sourceLineageDigest` is retained. Every duplicate returns `audit-efficiency-comparison-duplicate-identity` with the duplicate axis and comparison index before an inflated `sampleCount` or measured reduction percentage is emitted. Re-run the complete metrics tests after the remediation so provenance, unavailable-value handling, quality floors and advisory-only authority remain unchanged. Do not claim detection when every declared provenance field is fraudulently replaced.

## EV27-PUBLICATION

Run full suite, architecture, neutrality, documentation, schema and publication gates at the exact candidate.
