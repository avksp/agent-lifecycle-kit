# Bug Forensics Profile

Bug Forensics is an optional quality profile for tasks that explicitly ask to
find or fix a bug, regression, flaky failure, incident, or security bug. It is
disabled by default and does not change ordinary feature-work flow.

The profile requires the agent to prove this chain:

```text
symptom -> reproduction -> failure fingerprint -> hypotheses -> root cause -> minimal fix -> regression proof -> no collateral damage
```

## Phase 1 Contracts

- `agent-bug-forensics-profile.v1`: disabled-by-default profile declaration.
- `agent-bug-reproduction-receipt.v1`: proves the bug reproduces before a
  patch by recording a failing command and artifact digests.
- `agent-failure-fingerprint.v1`: stable failure identity based on exception,
  assertion, log pattern, stack top, and affected symbols. It can reference
  `findingId` and `rootCauseDigest` from proof-integrity evidence.
- `agent-failure-classification-receipt.v1`: neutral failure class,
  confidence, matched evidence and digest provenance.
- `agent-bug-hypothesis-ledger.v1`: accepted and rejected hypotheses plus the
  minimal-patch gate.
- `agent-regression-proof-receipt.v1`: proves the same fingerprint is red
  before the fix and green after it.
- `agent-bug-forensics-gate-receipt.v1`: workflow gate result for active or
  skipped profile use.
- `agent-bug-forensics-audit.v1`: audit summary for the gate receipt.

Bug Forensics reuses `agent-fix-impact-receipt.v1` from proof integrity for
behavior changes, preserved behavior, validation evidence and collateral damage.
It does not define a competing fix-impact schema.

## Activation

The profile activates only when a task explicitly sets `qualityProfile:
bug-forensics`, includes `bug-forensics` in `qualityProfiles`, or sets
`bugForensics.enabled: true`. A normal feature task receives a `SKIPPED` gate.

## Cross-Check

High-risk bug fixes can request a secondary review through the Release 1.12
cross-check profile. It remains token/resource-capped, not USD-canonical, and
advisory unless the frozen plan explicitly opts into blocking behavior.

Failure classification and flake signals can be attached to the gate receipt.
When a security or race classification is combined with S2/security task risk,
the gate requires cross-check evidence instead of silently accepting a weaker
review path.

## Recipes

Bug Forensics recipes are optional metadata for common defect-repair stages:

- `issue-classification`: decide the defect class and whether the profile is
  needed.
- `reproduction`: prove the bug is red before code changes and bind artifacts
  by digest.
- `investigation`: maintain accepted and rejected hypotheses and minimal-patch
  scope.
- `validation`: prove same-fingerprint red-to-green behavior and fix impact.
- `review`: validate the gate receipt and optional cross-check evidence.

Recipes do not introduce new receipt schemas. They reference the existing
Bug Forensics, proof-integrity and cross-check receipts, stay disabled by
default and use tokens/resources rather than mandatory USD cost.

## Deferred Analysis

Suspect graph remains optional. Flake signals and failure classification can be
recorded now, but they do not replace reproduction, fingerprint, hypothesis
ledger, regression proof or fix-impact evidence.
