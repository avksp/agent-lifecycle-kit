# Release 2.7: Review efficiency and evidence provenance

Status: `FROZEN / READY_FOR_IMPLEMENTATION`
Tier: `S2`
Depends on: accepted Release 2.6
Base: `main @ 30e2f2a55a2b8d959fa22b884e122952a2711ff7` (`v2.6.0`)

## Goal

Reduce repeated audit work using verified outcomes and independent samples without executing untrusted reviewer commands or accepting unresolved findings.

## User outcome

Audit rounds have explicit budgets and terminal dispositions, finding reproduction is routed only through approved checks, and statistical evidence proves where its samples came from and whether the sample can support the claimed threshold.

## Scope

1. Validate `maxPlanReviewRounds` as an integer from 1 through 10 and enforce it in Review Mesh synthesis; count participation only when a schema-valid `agent-review-verdict.v1` is bound to a complete, blocking-eligible `agent-external-job-result.v1` from a successful terminal job.
2. On round-budget exhaustion with an open `MEDIUM`, `HIGH`, `CRITICAL` or `BLOCKER` finding, return `REPLAN_REQUIRED`, `SPLIT_REQUIRED`, `OPERATOR_DECISION` or `BLOCKED`; never synthesize acceptance. Review agreement does not close a finding.
3. Replace duplicated incomplete Medium-or-higher filters with one canonical blocking set (`BLOCKER`, `CRITICAL`, `HIGH`, `MEDIUM`) across the existing review, implementation-audit, completion, finalization and plan-package gates.
4. Convert reviewer reproduction suggestions into advisory finding-check proposals; execute only a frozen approved check identity/profile through existing shell-free boundaries.
5. Produce a batch disposition with confirmed, rejected, unavailable and approval-required findings plus immutable evidence links. A rejected false positive is non-blocking only through its matching immutable `REJECTED` disposition; a confirmed, unavailable, approval-required or undisposed open `MEDIUM+` finding remains blocking regardless of its Review Mesh list.
6. Require source class, derivation identity, sample identity, source revision/lineage and independence statement for statistical/error-rate evidence; validate unique current samples against the declared method.
7. Add audit metrics for tokens/time per confirmed finding, no-final-verdict share, rejected-finding share and post-audit-remediation share while preserving quality floors.
8. Reproduce the accepted Release 2.6 accounting shape as a portable tracked fixture; use it as an observed baseline without inventing a percentage reduction target from one release.

## Non-goals

- executing command text returned by a model;
- limiting security review to four rounds and then accepting;
- auto-applying an audit optimization profile;
- requiring statistical provenance for ordinary non-statistical evidence;
- replacing Review Mesh, `agent-review-verdict.v1`, finding-check or external-job contracts;
- turning a findings-only Review Mesh import into reviewer participation;
- claiming an optimization percentage from the single Release 2.6 baseline.

`maxPlanReviewRounds` governs bounded plan/Review Mesh audit synthesis. It does not replace task-attempt policy: ordinary task rework remains governed by `maxTaskAttempts`. Release 2.7 closes the existing `CRITICAL`-severity omission everywhere the current product claims that an open Medium-or-higher finding blocks review, implementation audit, completion, finalization or package acceptance.

Review Mesh `acceptedFindings`, `rejectedFindings` and `unresolvedFindings` are synthesis buckets, not closure authority. Round evaluation joins every imported finding to exactly one immutable disposition. An open `MEDIUM+` finding blocks unless its disposition is `REJECTED`; synthesis `PASS`, reviewer agreement, transport success and process exit status cannot override that rule.
