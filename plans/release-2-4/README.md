# Release 2.4: Optional security analysis profile

Status: `CHANGES_REQUIRED / S2 REMEDIATION PENDING`  
Tier: `S2`  
Depends on: accepted Release 2.3 merge, rooted in the mandatory Release 2.0 baseline

Target: `2.4.0`; the canonical, Git-visible package is under
`plans/release-2-4/`. Runtime task artifacts remain under the ignored
`tasks/release-2-4/` mirror and `work/release-2-4/` evidence directory.

## Goal

Compose existing bug-forensics, review and evidence primitives into an optional security analysis profile with threat, exploitability, remediation and verification stages.

## User outcome

Security work receives reproducible evidence and stricter review without burdening ordinary feature tasks.

## Activation condition

The pre-implementation activation record authorizes one bounded, read-only
security case. Before freeze and release acceptance, the candidate must run
the complete profile against the safe fixture, including the no-write
investigation stage, the manifest-to-task authority bridge, and independent
verification. The pre-implementation record is not substituted for that
candidate evidence.

## Scope

1. Define an optional security analysis profile with threat model, suspected finding, exploitability evidence, deduplication, remediation and verification stages.
2. Define normalized security finding and SARIF mapping with stable IDs, severity, confidence, source revision and redacted locations.
3. Require explicit plan opt-in, sandbox and budgets for any active reproduction; safe static or synthetic evidence remains the default.
4. Require a separate verification assignment for accepted high-severity remediation at the authoritative task-acceptance boundary and preserve failed or disputed evidence.
5. Document safe security analysis in English and Russian, including authorization and disclosure boundaries.
6. Preserve the accepted mandatory baseline through Release 2.0, reconcile separately accepted candidates and require a safe end-to-end security fixture before freeze.
7. Materialize the `extensions.securityAnalysis.implementationAudit` policy into
   each adopted task and enforce it at `accept_task`; a high-severity
   remediation cannot be accepted from implementer evidence alone.

## Non-goals

- running exploit code by default
- turning ALK into a vulnerability scanner
- automatically modifying code after research
- making security stages mandatory for ordinary tasks

## Release boundary

This package is activated by the bounded read-only security-analysis case in
`activation-evidence.md`. It cannot be frozen until the latest accepted
Release 2.3 merge is the plan base, the package is reproducible from the
Git-visible `plans/release-2-4/` root, the package is reconciled with accepted
optional candidates, an independent S2 audit is complete and the final
revision is locked. English and Russian product documentation are required
implementation artifacts.
