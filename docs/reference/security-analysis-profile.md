# Optional security analysis profile

ALK provides an optional, provider-neutral profile for bounded security
investigation. It organizes threat modeling, finding normalization,
exploitability evidence, deduplication, remediation and independent
verification. It is not a vulnerability scanner and it does not run exploit
code by default.

## Control owners and limits

| Control | Owner | Check | Limit |
| --- | --- | --- | --- |
| Disabled profile, execution-gate receipts and finding validation | [quality/security_analysis.py](../../src/agent_lifecycle/quality/security_analysis.py) | [profile and gate tests](../../tests/quality/test_security_analysis.py) | A receipt validates declared authorization and limits; ALK does not supply a sandbox or run an exploit. |
| File import and recognized-secret refusal | [imports/security_findings.py](../../src/agent_lifecycle/imports/security_findings.py), [shared import guard](../../src/agent_lifecycle/imports/planning.py), [authority I/O](../../src/agent_lifecycle/contracts/authority_io.py) | [import tests](../../tests/imports/test_security_findings.py), [CLI output tests](../../tests/cli/test_import_security_boundaries.py) | `import-sensitive-content` refuses recognized categories in content and metadata before output; not every possible secret. Bounded file reads reject links/identity changes and retain `security-analysis-import-too-large`. |
| Independent verification for covered remediation | [workflow/task_transitions.py](../../src/agent_lifecycle/workflow/task_transitions.py), [security_analysis_acceptance_blocker](../../src/agent_lifecycle/quality/security_analysis.py) | [acceptance tests](../../tests/workflow/test_security_analysis_profile.py) | Enforced only for the adopted security-analysis policy and its covered severity; an imported finding never accepts a task. |

See the [current security map](../security/release-security.md) for CI guards
and host limits. `GUIDANCE_ONLY` is not host enforcement, and optional analysis
does not qualify protected closure/operator routes or prove safety on all hosts.

## Default boundary

The profile is `OPTIONAL` and disabled by default. A profile or imported
finding never grants workflow authority, accepts a task or starts a host
process. Findings are explicitly untrusted until their source revision,
source lineage and redacted locations pass validation.

The default execution policy is:

- explicit frozen-plan opt-in is required;
- a sandbox receipt and bounded authorization are required before any active
  reproduction;
- live model, network and host-process calls are disabled by default;
- imported evidence cannot promote itself to a vulnerability or production
  decision.

The normal read-only path is enough for static evidence:

Replace `SOURCE_REVISION` with the revision analyzed by `findings.sarif`.
Use fresh output paths; the commands create evidence files without changing
workflow state. `--profile` on the report is a boolean flag that includes
the default profile, not a file argument. The report imports the same raw
findings source; validation does not turn that source into trusted evidence.

```bash
agent-lifecycle quality security-profile --out work/security-profile.json
agent-lifecycle import security-findings \
  --source findings.sarif \
  --source-revision "SOURCE_REVISION" \
  --expected-source-revision "SOURCE_REVISION" \
  --out work/security-findings.json
agent-lifecycle quality security-finding-check \
  --candidate work/security-findings.json \
  --expected-source-revision "SOURCE_REVISION" \
  --out work/security-findings-validation.json
agent-lifecycle report security-analysis \
  --finding findings.sarif \
  --profile \
  --source-revision "SOURCE_REVISION" \
  --expected-source-revision "SOURCE_REVISION" \
  --out work/security-analysis-report.json
```

The import accepts normalized findings and bounded SARIF input. The report
retains validation status, finding IDs and evidence links, while keeping
`trusted: false`, `authorityClaimed: false` and
`productionPromotionClaimed: false`.

## High-severity remediation

The plan may copy `extensions.securityAnalysis.implementationAudit` into each
adopted task. When the policy covers high severity, the real task-acceptance
boundary rejects implementer-only evidence with
`security-analysis-verification-required`. Acceptance requires a fresh,
independent verification assignment whose run, task, attempt, plan and source
lineage match the adopted task. A Review Mesh packet can provide the reviewer
assignment, but the lifecycle acceptance gate remains authoritative.

Failed, stale, disputed or incomplete evidence remains evidence of the failed
check; it is not silently converted into acceptance. Rework must use the
existing workflow transitions and a new attempt rather than editing a prior
receipt.

## Safe execution and disclosure

An imported finding or profile alone cannot execute a reproduction. An active
step must be declared by the frozen plan, authorized for the exact operation,
bound to a sandbox receipt and limited by attempts, invocations, wall time and
evidence bytes. The provider-specific command, model and credentials remain
outside the core profile.

Do not put secrets, private incident details, exploit payloads or raw host
output into portable evidence. Use repository-relative paths or public
HTTP(S) locators after validation. Local absolute paths, file URIs, credentials
and secret-like locator values fail closed or are redacted according to the
shared locator contract.

## Contracts

The main contracts are:

- `agent-security-analysis-profile.v1`;
- `agent-security-finding.v1` and its import/validation envelopes;
- `agent-security-execution-gate.v1`;
- `agent-security-verification-assignment.v1`;
- `agent-security-analysis-audit.v1`.

The profile is an optional evidence layer over the existing ALK workflow. It
does not create a second state machine, replace the frozen plan or claim that
an external analyzer ran when only an imported result was supplied.

See also [public locators and redaction](public-locators-and-redaction.md),
[implementation audit](implementation-audit.md), and [external verification
checks](external-verification-checks.md).
