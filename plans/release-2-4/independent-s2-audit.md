# Independent S2 audit: Release 2.4

Audit mode: pre-implementation, read-only review of the activated revision.
Source revision: `7d4eb79e53821d2bd2f3766f2d6fb3610e408149`.
Plan revision: 4.

## Verdict

`CHANGES_REQUIRED`

Structural checks pass, but one acceptance path is not connected to the
authoritative workflow and the current write-set leaves existing regression
surfaces outside the executor's repair boundary.

## Findings

### H1 - Independent security verification is not connected to acceptance

**Affected criteria:** `AC93-REVIEW`, `AC93-PROFILE`.

The plan says that accepted high-severity remediation requires a separate
verification assignment, but its write-set changes only
`review_mesh/assignments.py` and the generic Bug Forensics gate. The actual
workflow acceptance path remains in `workflow/task_outcomes.py` and the
implementation/finalization audit gates. Those gates consume
`implementationAudit` and `reviewMesh` configuration only when the state or
manifest explicitly supplies it:

- `src/agent_lifecycle/workflow/implementation_audit_gate.py:13-33`
  checks implementation-audit flags;
- `src/agent_lifecycle/workflow/review_mesh_gate.py:17-105` treats Review Mesh
  as required only when its configuration says so;
- `src/agent_lifecycle/audit/implementation.py:575-583` reads the optional
  task/state Review Mesh configuration;
- `src/agent_lifecycle/workflow/task_outcomes.py:223-293` accepts a task from
  the reviewed outcome path.

`build_bug_forensics_gate_receipt()` can require a cross-check for a security
classification, but that is not the same contract as a separate verification
assignment for accepted high-severity remediation. No planned acceptance test
currently proves that an implementer-only result is rejected at the real task
acceptance/finalization boundary.

**Required correction:** add the smallest authoritative bridge, or explicitly
bind the new security profile to the existing implementation-audit/Review Mesh
gate. Add a negative end-to-end test: a high-severity security remediation with
only the implementing result must fail; the same task with a fresh,
lineage-matched independent verification assignment must pass. The test must
also prove that a profile or imported finding alone cannot authorize execution.

### M1 - Existing regression tests are outside the write-set

**Affected workstreams:** `WS93-01`, `WS93-02`.

The plan changes existing implementation surfaces while creating parallel test
files, but does not assign the existing direct regression suites:

- `tests/contracts/test_bug_forensics_schemas.py`
- `tests/contracts/test_contracts.py` (schema registry contract)
- `tests/quality/test_bug_forensics_profile.py`
- `tests/quality/test_bug_forensics_recipes.py`
- `tests/workflow/test_bug_forensics_gates.py`
- `tests/review_mesh/test_assignments.py`
- `tests/review_mesh/test_independent_evidence.py`
- `tests/cli/test_quality_observability_commands.py`

The full unittest discovery command will detect a regression, so this is not a
silent coverage hole. It is an execution-authority problem: a worker can break
an existing contract and be unable to update its direct regression test,
causing an avoidable stop or an unjustified scope expansion.

**Required correction:** include the directly affected existing tests in the
appropriate workstream, or record an explicit owner and a deterministic reason
for keeping each one outside the write-set. Hub tests that only perform global
discovery may remain outside with that rationale.

### M2 - Evidence routes are too abstract for security claims

`EV93-PROFILE`, `EV93-FINDINGS` and `EV93-EXECUTION` contain outcome prose but
do not identify fixture names, command inputs, mutation fields or expected
error codes. `EV93-REVIEW` mentions independent mutations generically without
specifying the high-severity acceptance case from H1.

**Required correction:** enumerate deterministic positive and negative cases
for profile-only execution, imported-finding authority, source-revision drift,
private-path/secret redaction, severity bounds, replay and independent
verification. Each case needs an expected status and stable blocker code.

## Checks performed

- plan completeness: PASS;
- acceptance checklist: PASS, 6/6;
- references check: PASS, 0 repository references;
- activation evidence: present and tied to the 2.3 merge;
- activation fixture: tracked synthetic security scenario with zero live model
  invocations;
- existing security, Bug Forensics, audit and benchmark boundary tests: PASS;
- tracked-release neutrality scan: PASS, zero findings;
- no new provider, network, shell or external-tool runtime was introduced by
  the plan itself.

## Coverage matrix

| Requirement | Acceptance | Workstream | Evidence | Audit status |
| --- | --- | --- | --- | --- |
| `R93-PROFILE` | `AC93-PROFILE` | `WS93-01` | `EV93-PROFILE` | blocked by H1 |
| `R93-FINDINGS` | `AC93-FINDINGS` | `WS93-01/02` | `EV93-FINDINGS` | insufficient detail, M2 |
| `R93-EXECUTION` | `AC93-EXECUTION` | `WS93-02` | `EV93-EXECUTION` | insufficient detail, M2 |
| `R93-REVIEW` | `AC93-REVIEW` | `WS93-02` | `EV93-REVIEW` | blocked by H1 |
| `R93-DOCUMENTATION` | `AC93-DOCUMENTATION` | `WS93-03` | `EV93-DOCUMENTATION` | structurally covered |
| `R93-ACTIVATION` | `AC93-ACTIVATION` | `WS93-03` | `EV93-ACTIVATION` | PASS for activation |

## Freeze decision

Do not generate `plan.lock.json` or start implementation until H1 is closed,
M1 is resolved, M2 has concrete evidence cases, the plan is raised to the next
revision and the complete S2 review is repeated.

## Remediation re-audit: plan revision 5

The plan was amended without changing its intent:

- H1 is addressed at the plan level by assigning
  `workflow/implementation_audit_gate.py` and requiring a real task-acceptance
  negative/positive pair with the stable
  `security-analysis-verification-required` blocker;
- M1 is addressed by assigning the direct existing contract, Bug Forensics,
  Review Mesh and observability regression suites;
- M2 is addressed by naming fixture classes, mutation dimensions and expected
  blocker codes in the evidence plan.

Repeated checks remain PASS: completeness, acceptance 6/6, references 0 and
the activation fixture/neutrality boundary. No new ownership or dependency
conflict was found in the revised manifest.

This is a static remediation re-audit, not an independent reviewer quorum. The
package is therefore `READY_FOR_EXTERNAL_S2_CONFIRMATION / NOT_READY_TO_FREEZE`.
An independent reviewer must confirm the revised authority bridge and then the
final plan lock may be generated. Implementation must not start before that
confirmation.

## Independent S2 review: revision 5 baseline

An independent reviewer inspected the package and current source without using
the preceding audit as its basis. The result is `CHANGES_REQUIRED`; no source,
plan or Git index files were changed by the reviewer.

### H1 - High: the authority bridge still is not machine-enforced

The manifest had only declarative security gates. The runtime implementation
audit gate is conditional on a flag in state, task or manifest, and plan
adoption did not materialize the requirement into the adopted task. Therefore
an implementer-only high-severity remediation could reach `accept_task` without
the required independent verification.

Relevant surfaces reviewed:

- `src/agent_lifecycle/workflow/implementation_audit_gate.py`;
- `src/agent_lifecycle/workflow/plan_adoption.py`;
- `src/agent_lifecycle/workflow/task_transitions.py`;
- `src/agent_lifecycle/workflow/task_outcomes.py`.

Required correction: define a machine-readable policy in the manifest,
propagate it during adoption, and test the negative and positive cases through
`apply_task_review_outcome` and `accept_task`.

### H2 - High: activation evidence does not execute the declared profile

The current fixture is a safe boundary record, but the conformance test checks
fixture inventory, hashes and taxonomy without executing `steps` and
`expectedOutcome`. The activation record itself correctly says that the
current code does not yet implement Release 2.4, so it cannot serve as the
complete profile acceptance receipt.

Required correction: keep the pre-implementation record as authorization only,
and require a candidate-time deterministic no-live conformance run with a
per-step receipt, zero model/network/host calls and zero writes outside the
evidence directory.

### H3 - High: the package was not Git-reproducible

The prior canonical package lived only under ignored `tasks/`, with no lock.
The plan now has a Git-visible canonical root at `plans/release-2-4/`; runtime
artifacts remain under ignored `tasks/release-2-4/` and `work/release-2-4/`.
The final lock will be created only after the revised package is independently
audited and committed.

### M1 - Medium: CLI write-set omitted real routing surfaces

The plan named observability parser/dispatcher modules but did not explicitly
cover the existing `quality` and `import` routes in `cli/parsers.py` and
`cli/dispatch_contracts.py`, nor the adoption and task-acceptance surfaces.
The revised write-set includes the real authority and regression-test modules;
the release implementation must update only the routes needed by the profile.

### M2 - Medium: evidence was not machine-linked to acceptance

The revised evidence plan names the exact task-outcome route, adopted-task
policy, assignment identity, run/task/plan/source lineage and evidence output
path. It also requires stable blocker codes and digests for both the rejecting
and accepting cases.

### M3 - Medium: duplicate retry budget

The independent review found `orchestration.maxTaskAttempts = 3` and
`budgetPolicy.maxTaskAttempts = 10`. The revised manifest keeps the single
authoritative value in `orchestration.maxTaskAttempts` and documents that
`budgetPolicy` must not redefine it.

## Remediation status: revision 6

The package revision is now `7`. The canonical package is under
`plans/release-2-4/`; the local `tasks/release-2-4/` copy is a compatibility
mirror. The write-set includes plan-manifest schema/adoption/task-transition
authority, direct acceptance regressions and deterministic conformance
coverage, plus the existing CLI routing surfaces. The acceptance and evidence
documents require the manifest-to-task bridge, declared review artifact paths
with `independentEvidenceIds`, and candidate-time execution of every
activation fixture step.

Repeated completeness, acceptance, reference and package-path checks must pass
on this revision. This entry is still a remediation record, not a final
independent S2 approval. A fresh independent S2 confirmation is required
before `plan.lock.json` and implementation.
