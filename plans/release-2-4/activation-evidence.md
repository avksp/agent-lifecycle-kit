# Activation evidence: Release 2.4

Status: `ACTIVATED / BOUNDED / PRE-IMPLEMENTATION`

## Authorized use case

The operator authorized a read-only security analysis of ALK after the Release
2.3 merge. The scope is the repository itself, the current source revision and
the tracked safe fixtures below. No real secret, private incident detail,
exploit payload or external host process is included.

Task identifier: `SEC-2.4-ACTIVATION-01`.

Source revision: `7d4eb79e53821d2bd2f3766f2d6fb3610e408149` (Release 2.3 merge).

## Reproducible safe fixture

The bounded scenario is `fixtures/synthetic/s2-security-01.json`. It contains
only expected fail-closed outcomes for stale or forged receipts, cyclic DAGs,
forbidden writes and unsupported adapter operations. It declares
`liveModelInvocations: 0` and does not contain executable exploit material.

The existing Bug Forensics reference task is
`benchmarks/reference-tasks/rt03-bug-forensics/`; its oracle requires a
reproduction receipt, regression proof and proof validation. These tracked
fixtures demonstrate the security-adjacent lifecycle gap without making the
new profile mandatory for ordinary tasks.

This record authorizes activation; it is deliberately not the complete
Release 2.4 acceptance receipt. The latter must be generated after
implementation at
`work/release-2-4/evidence/activation/complete-profile.json` by executing all
fixture `steps` and checking every `expectedOutcome` through the deterministic
no-live conformance runner. The final receipt must include manifest, adopted
task, plan and source digests, per-step expected/actual outcomes, and explicit
zero counts for model, network, host-process and out-of-evidence writes.

## Verification record

The investigation was read-only with respect to `src/`, `tests/`, `docs/`,
policies and package metadata. The only generated output was the local report
under `work/release-2-4/activation/`.

| Check | Command or source | Result |
| --- | --- | --- |
| Security boundary regression | `python -m unittest tests.security.test_release_security -q` | 2 tests, `OK` |
| Bug Forensics workflow boundary | `python -m unittest tests.workflow.test_bug_forensics_gates -q` | 5 tests, `OK` |
| Audit and reference-task contracts | `python -m unittest tests.audit.test_bug_forensics_audit tests.benchmarks.test_oracles -q` | 9 tests, `OK` |
| Repository neutrality | tracked-release scan with `--require-zero-findings` | exit 0, `findings: []` |
| Live execution | fixture and commands above | no model, network or host launch |

The security suite and the Bug Forensics/audit suites were run as separate
verification commands. The results are independent checks of the boundary,
not a claim that the current code already implements the Release 2.4 profile
or that the fixture steps have already been executed by the future profile.

## Observed lifecycle gap

The current optional Bug Forensics path can classify and gate a security-shaped
defect, but it does not provide one bounded contract for:

- a normalized security finding with stable severity, confidence, source
  revision and redacted locator;
- importing an untrusted finding or mapping it to SARIF without granting it
  workflow authority;
- separating safe static or synthetic evidence from explicitly authorized
  reproduction and assigning independent verification for accepted remediation.

The existing security and Bug Forensics tests prove the surrounding boundaries;
the tracked fixture proves the negative outcomes. The gap is therefore an
optional evidence and review profile, not a justification for a scanner,
background service or automatic remediation.

## Activation boundary

Release 2.4 is activated only for this bounded, read-only security-analysis
use case. The implementation must keep ordinary task routing unchanged, keep
workflow state as the only authority, require explicit plan opt-in for active
reproduction, preserve failed and disputed evidence, and require a separate
verification assignment for accepted high-severity remediation.

This evidence does not report a vulnerability and does not authorize exploit
execution. It only establishes that the optional profile addresses a real
missing contract in the existing ALK workflow.
