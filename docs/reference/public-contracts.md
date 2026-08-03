# Public contracts

Public contract policy keeps ALK outputs predictable for adapters, release
checks and operator scripts.

`agent-public-contract-policy.v1` lists the current public schemas, CLI JSON
outputs and compatibility rules. The policy is generated from the bundled
schema registry, so it is small enough for compact review and still points to
the authoritative full schemas.

```bash
agent-lifecycle contract policy --out <public-contract-policy.json>
agent-lifecycle contract check --policy <public-contract-policy.json>
```

The compatibility rules are intentionally narrow:

- public schema ids are immutable;
- existing required fields must not change meaning in-place;
- compatible additions use optional fields or a new schema id;
- deprecated input shapes remain accepted until a replacement is documented;
- CLI commands keep compact JSON envelopes with stable `schemaVersion` values;
- failures use `agent-lifecycle-error.v1` with a stable `code`.

Adapters should branch on `schemaVersion` and `code`, not prose output.
Large-model reviews can inspect the full schema body through `schema show`;
small local models can use the policy receipt as a compact map of what is
stable.

## Core lifecycle controls

The core lifecycle surface covers completion, goal continuity, runner state,
follow-up tracking, worktree isolation, adapter event capture, review verdicts
and optional quality/reporting controls.

Stable schema ids:

- `agent-completion-check-receipt.v1`
- `agent-completion-gate-receipt.v1`
- `agent-completion-gate-validation.v1`
- `agent-goal-record.v1`
- `agent-objective-snapshot.v1`
- `agent-runner-state.v1`
- `agent-runner-snapshot.v1`
- `agent-managed-lifecycle-next-action.v1`
- `agent-managed-lifecycle-runner-receipt.v1`
- `agent-no-model-call-scan.v1`
- `agent-plan-completeness-profile.v1`
- `agent-plan-completeness-profile-validation.v1`
- `agent-plan-completeness-validation.v1`
- `agent-implementation-audit-report.v1`
- `agent-implementation-audit-report-validation.v1`
- `agent-final-implementation-audit.v1`
- `agent-final-implementation-audit-validation.v1`
- `agent-follow-up-register.v1`
- `agent-follow-up-summary.v1`
- `agent-worktree-isolation-policy.v1`
- `agent-worktree-attempt-receipt.v1`
- `agent-worktree-writeback-receipt.v1`
- `agent-worktree-writeback-receipt-validation.v1`
- `agent-adapter-event-stream-receipt.v1`
- `agent-adapter-event-capture-validation.v1`
- `agent-review-verdict.v1`
- `agent-review-routing-summary.v1`
- `agent-optional-quality-pack.v1`
- `agent-behavior-check-run.v1`
- `agent-task-template-library.v1`
- `agent-task-template-library-validation.v1`
- `agent-task-template-render.v1`
- `agent-bug-forensics-recipe-library.v1`
- `agent-bug-forensics-recipe-validation.v1`
- `agent-diagnostic-bundle.v1`
- `agent-readonly-status-view.v1`
- `agent-workflow-event-feed.v1`
- `agent-lifecycle-progress-view.v1`
- `agent-lifecycle-quality-floor-decision.v1`
- `agent-adaptive-lifecycle-policy-request.v1`
- `agent-adaptive-lifecycle-policy-decision.v1`
- `agent-adaptive-lifecycle-policy-decision-validation.v1`
- `agent-small-model-task-packet.v1`
- `agent-small-model-task-packet-index.v1`
- `agent-small-model-output-contract.v1`
- `agent-small-model-task-result.v1`
- `agent-small-model-output-validation.v1`
- `agent-small-model-packet-compile-result.v1`
- `agent-task-outcome-index.v1`
- `agent-quality-cost-signals.v1`
- `agent-quality-cost-signals-summary.v1`

`completionCheck` binds observable completion evidence. The completion gate is
a deterministic stop/continue/escalate/split/follow-up decision over current
evidence. Optional quality packs and read-only reports add bounded evidence,
but they do not replace source-of-truth lifecycle artifacts. Event feeds and
progress views are projections over existing state/receipts; they do not start
model calls, spend tokens, or mutate state. The managed lifecycle runner adds a
typed read-only `workflow run` projection that checks frozen plan/state lineage
and returns the next host-owned action. Implementation audit reports bind task
results, independent reviews, ownership, evidence and sandbox checks before a
task or run can pass a mandatory audit gate.
Plan completeness validation checks the selected SDD tier before audit, so
small plans can stay compact while risky S2 work still has requirements,
acceptance, evidence routes, ownership, budgets, context limits and final gates.

Adaptive lifecycle policy chooses the lightest safe mode from neutral
task/risk/evidence/resource inputs. It is advisory by default; automatic
selection requires explicit opt-in and cannot choose below the quality floor.
It does not use provider/model names or live currency lookup.

Quality-cost learning builds local, advisory signals from explicit lifecycle
receipts. It groups outcomes by task shape, lifecycle mode, route class and
profile, then records token, wall-time, tool-call, retry and blocker-rate
signals. It never starts telemetry, requires USD fields, builds
provider/model leaderboards or mutates policy automatically.

Small-model packets compile frozen task packets into a narrower implementation
surface with exact write scope, compact context receipts and required output
contracts. They cannot expand authority or satisfy critical review by
themselves.

## Evidence integrity

The proof-integrity surface is additive and opt-in. It is used when a run or
final audit explicitly requires stronger evidence for a bug fix, regression or
high-risk change.

Stable schema ids:

- `agent-proof-finding.v1`
- `agent-root-cause-evidence.v1`
- `agent-fix-impact-receipt.v1`
- `agent-failure-classification-receipt.v1`
- `agent-failure-classification-validation.v1`
- `agent-receipt-hash-chain.v1`
- `agent-hash-chain-migration-policy.v1`
- `agent-proof-integrity-receipt.v1`
- `agent-proof-integrity-validation.v1`

`agent-fix-impact-receipt.v1` is the canonical fix-impact contract. It binds
changed files, related finding ids, root-cause digests, behavior changes,
preserved contracts, validation evidence and collateral-damage checks.

`agent-failure-classification-receipt.v1` classifies failures into neutral
classes such as edge-case, API contract, race, flaky test, security bug or
unknown. It records confidence, matched evidence and digest provenance without
provider/model names in core.

## Sandbox boundaries

The sandbox-boundary surface is additive and opt-in for tasks that require
runtime containment evidence.

Stable schema ids:

- `agent-sandbox-receipt.v1`
- `agent-sandbox-receipt-validation.v1`
- `agent-sandbox-requirement.v1`
- `agent-sandbox-requirement-validation.v1`
- `agent-sandbox-capability.v1`
- `agent-sandbox-capability-validation.v1`

`agent-sandbox-receipt.v1` is distinct from
`agent-worktree-attempt-receipt.v1`: worktree receipts govern repository write
scope, while sandbox receipts govern runtime filesystem, network, process,
environment and enforcement-source evidence. `UNKNOWN` is a valid explicit
capability state, but high-risk required policy accepts only configured passing
sandbox statuses.

Partial containment and credential proxy boundaries remain details inside
`agent-sandbox-receipt.v1`; no execution-sandbox alias schema is introduced.

## Adapter capability bench

Adapter capability bench contracts are release-time drift detectors for live
host conformance. They plan and validate coverage, but they do not start live
calls or promote maturity.

Stable schema ids:

- `agent-adapter-probe-profile.v1`
- `agent-adapter-probe-plan.v1`
- `agent-adapter-probe-evidence-validation.v1`
- `agent-adapter-package-discovery.v1`

`agent-adapter-probe-plan.v1` keeps `liveCallsStarted: false`,
`promotionDecision: NOT_EVALUATED`, `maturityChangeClaimed: false` and
`productionPromotionClaimed: false`.

`agent-adapter-package-discovery.v1` is advisory release inspection over
source-tree descriptors and capability manifests. It cannot override descriptor
maturity or claim production promotion.

## Import interop and episode retrieval

The import interop surface maps external dialects into reviewed ALK draft
artifacts. It never treats imported content as trusted source of truth.

Stable schema ids:

- `agent-import-dialect-profile.v1`
- `agent-import-dialect-profile-validation.v1`
- `agent-episode-index.v1`
- `agent-episode-index-validation.v1`
- `agent-episode-retrieval.v1`

`agent-import-dialect-profile.v1` requires `sourceTrusted: false`,
`requiresReview: true` and `freezeBlocked: true`. Imported artifacts can carry
`nativeDialectProfileDigest`, but that digest is provenance, not review
approval.

Generic external workflow and agent/harness imports reuse
`agent-import-dialect-profile.v1` with family/profile metadata. Workflow-family
imports produce reviewable requirements and validation hints without executing
imported nodes. Agent-family imports keep provider, model, auth, environment and
tool hints as host-local redacted metadata; they are not portable defaults.

`agent-episode-retrieval.v1` is a bounded context projection over explicit
receipt/session artifacts. Results keep artifact digests and report
`chainVerified` only when a supplied hash chain contains the same path and
digest; otherwise they are `chainUnchecked`.

## Runner recovery and optional cross-check

Runner recovery contracts are additive receipts for multi-attempt work. They do
not replace workflow state or the controlled runner state.

Stable schema ids:

- `agent-runner-attempt-snapshot-receipt.v1`
- `agent-runner-attempt-snapshot-receipt-validation.v1`
- `agent-worker-lease-receipt.v1`
- `agent-worker-lease-receipt-validation.v1`
- `agent-phase-resource-measurement.v1`
- `agent-phase-resource-measurement-validation.v1`
- `agent-cross-check-profile.v1`
- `agent-cross-check-profile-validation.v1`
- `agent-cross-check-receipt.v1`
- `agent-cross-check-receipt-validation.v1`
- `agent-runtime-policy-receipt.v1`
- `agent-runtime-policy-receipt-validation.v1`

`agent-phase-resource-measurement.v1` reuses the usage-export envelope for
phase-level tokens, duration and resource counters. It rejects monetary phase
fields; USD-cost is not required for local or non-metered models.

`agent-cross-check-profile.v1` is disabled by default, token/resource-capped and
advisory unless a plan explicitly opts into blocking use. Optional independence
evidence compares neutral host/model identity hashes; provider names are not
canonical.

`agent-runtime-policy-receipt.v1` distinguishes proven pre-execution
enforcement from advisory-only logging. `agent-worktree-writeback-receipt.v1`
records overlay apply/discard decisions and does not replace
`agent-sandbox-receipt.v1`.

## Bug forensics

Bug Forensics is an optional defect-repair profile. It is activated only by an
explicit task/profile marker and requires proof that the same failure is red
before the fix and green after it.

Stable schema ids:

- `agent-bug-forensics-profile.v1`
- `agent-bug-forensics-profile-validation.v1`
- `agent-bug-reproduction-receipt.v1`
- `agent-bug-reproduction-receipt-validation.v1`
- `agent-failure-fingerprint.v1`
- `agent-failure-fingerprint-validation.v1`
- `agent-failure-classification-receipt.v1`
- `agent-failure-classification-validation.v1`
- `agent-bug-hypothesis-ledger.v1`
- `agent-bug-hypothesis-ledger-validation.v1`
- `agent-regression-proof-receipt.v1`
- `agent-regression-proof-receipt-validation.v1`
- `agent-bug-forensics-gate-receipt.v1`
- `agent-bug-forensics-gate-validation.v1`
- `agent-bug-forensics-audit.v1`
- `agent-bug-forensics-audit-validation.v1`
- `agent-bug-forensics-recipe-library.v1`
- `agent-bug-forensics-recipe-validation.v1`

`agent-fix-impact-receipt.v1` remains the canonical fix-impact contract. Bug
Forensics references it instead of defining a competing schema. Cross-check, if
requested for a high-risk bug, reuses `agent-cross-check-receipt.v1` with
token/resource caps and without mandatory USD-cost accounting.

Bug Forensics recipes are metadata over the existing receipt chain. They are
optional, disabled by default and cannot introduce competing defect-repair
receipt schemas.
