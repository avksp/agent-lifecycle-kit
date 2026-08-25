# Evidence plan

## EV93-PROFILE

Run `security-profile-only` and `high-severity-without-verification` negative
fixtures. Expected blocker codes are
`security-analysis-profile-not-authorized` and
`security-analysis-verification-required`; no state or source file may be
written. The positive case must show the manifest extension
`extensions.securityAnalysis.implementationAudit` copied into the adopted
task and read by the acceptance path; a profile-only receipt is not authority
to accept a remediation.

## EV93-FINDINGS

Run positive and negative imports for a tracked source revision, a stale source
revision, a malformed severity/confidence pair, a private absolute locator and
a secret-like locator. Expected blocker codes are
`security-analysis-source-revision-mismatch`,
`security-analysis-severity-invalid`, `security-analysis-private-locator` and
`security-analysis-secret-value`.

## EV93-EXECUTION

Run profile-only, imported-finding-only and explicit-opt-in scenarios. The
first two must fail with `security-analysis-execution-authorization-required`;
the explicit scenario must still require a bounded sandbox receipt and remain
within the declared attempt, byte and wall-time limits.

## EV93-REVIEW

Run positive, boundary and adversarial fixtures. Mutate authority, source
lineage, limits, completeness, replay and verification assignment independently.
The implementing result without an independent verification assignment must
fail at task acceptance with `security-analysis-verification-required`.
A fresh assignment with matching run/task/plan/source revision, a distinct
reviewer identity and a passing Review Mesh/implementation-audit receipt must
pass through `apply_task_review_outcome` and `accept_task`. The fixture must
assert that the required policy is present in the adopted task, not merely in
the source manifest. Failed or disputed evidence remains immutable and
addressable by digest.

## EV93-DOCUMENTATION

Validate `docs/reference/security-analysis-profile.md` and `docs/ru/reference/security-analysis-profile.md`, navigation, terminology parity and optional-use examples.

## EV93-ACTIVATION

Use `activation-evidence.md` only as the pre-implementation authorization for
the read-only security-analysis case at source revision
`7d4eb79e53821d2bd2f3766f2d6fb3610e408149`. At the exact candidate, execute
all `steps` and `expectedOutcome` assertions in
`fixtures/synthetic/s2-security-01.json` via the deterministic conformance
runner and write
`work/release-2-4/evidence/activation/complete-profile.json`. The receipt must
record `liveModelInvocations: 0`, `networkCalls: 0`, `hostProcessCalls: 0`,
`writesOutsideEvidence: 0`, per-step expected/actual outcomes and the
manifest/task/plan/source digests. Only then run the complete predecessor,
architecture, neutrality, documentation and publication gates against the
exact candidate.
