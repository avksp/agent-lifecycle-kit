# Agent Lifecycle Kit documentation

Release 2.32 adds a shared advisory observation of process costs, paired EN/RU
manual checks, and shorter reading routes for eight selected stage cases. Process
means pipeline compliance plus coordination; useful work means implementation
plus product validation. Reported and confirmed subtotals retain their scope
and confidence. An attested subset does not establish whole-run completeness.
Missing whole-run shares and provider usage stay null/UNAVAILABLE. Existing
pipeline verdicts, limits and lifecycle authority retain their meaning.

The fixed source-reading comparison reduces plan authoring from 25,643 to
23,570 UTF-8 bytes (8.084%) and defect repair from 26,247 to 24,174 (7.898%).
Both miss the 10% engineering target. All seven complete role contracts and
skill routers are unchanged. These are selected-stage source bytes, not whole
host input or measured token/model savings. A fixed local comparison reduces
CLI/facade calls from two to one with identical state/event bytes; its wall time
can be higher. See [the CLI release notes](reference/cli.md#release-232-process-observations-and-reading-scope) for scope and refusal boundaries.

Release 2.31 strengthens supported-text secret checks, enforces global branch and critical-file coverage floors, and gives a bounded structural refusal for malformed legacy state. See [the 2.31 check boundaries](reference/cli.md#release-231-bounded-quality-checks).


Release 2.30 adds [bounded workflow history and recovery](reference/workflow-state-storage.md)
and [explicit authorization renewal](reference/cli.md#workflow-history-and-authorization-renewal-in-230).
The plugin supplies skills and documents; the Python package supplies the CLI.

Release 2.29 keeps full skill contracts, checks all seven roles and bundles
19 required static documents in the [portable plugin](reference/agent-plugins.md).
The [local writing profile](guides/controlled-technical-english.md) defines staged
reading and honest byte/word metrics; token savings and host enforcement are
not inferred.

This documentation describes the standalone lifecycle kit. ALK controls
completion of coding-agent work by keeping the requested result, reviewed plan,
bounded execution, evidence, review and final proof aligned. The external agent
solves the product task; ALK preserves the authority needed to verify or block
that result. It is host-neutral and does not depend on a source project.


Release 2.28 adds [bounded lifecycle and accounting baselines](reference/performance-and-resource-budgets.md#release-228-lifecycle-and-accounting-baselines). Repository tools measure real read-only operations and separate fixture preparation from operation and subprocess time. The Windows fixture comparison observed a 13.08% median reduction in one six-sample experiment; it is not a universal speed promise. All security and platform checks remain required.

## Release 2.18 security and compatibility

Read [OpenCode 1.x/2.x qualification and signing](adapters/opencode.md), [redaction policy](reference/public-locators-and-redaction.md) and [review examples](guides/code-review-workflows.md). Process stdin/output/Git reads share bounded deadlines and byte limits; identity capture disables external diff and textconv. Historical receipts remain unchanged. No host or model guarantee is inferred from CLI help.

## Release 2.17 workflow validation

Read [workflow completeness and recovery](reference/workflow-completeness.md) for explicit plan inputs, bounded writes, unfinished items and review interruption. Existing accounting and host-capability boundaries remain in force.

## Release 2.15 migration

Read the [authority-artifact migration notes](reference/cli.md#migrating-authority-artifacts-to-215)
and [authority boundaries](reference/authority-artifact-boundaries.md) before
updating existing plans and runtime output layouts.

## Locales

- [English documentation](README.md)
- [Русская документация](ru/README.md)

## Quick start

- [Install ALK and make the first run](guides/install-and-first-run.md)
- [Portable Agent Plugins package](reference/agent-plugins.md)
- [Agent Plugins client qualification](reference/agent-plugin-qualification.md)
- [Commands by task](guides/commands-by-task.md)
- [Runner migration for 2.x](guides/runner-migration-2.md)
- Official PyPI package for Python 3.11-3.15:
  `python -m pip install agent-lifecycle-kit==2.32.0` from
  [agent-lifecycle-kit](https://pypi.org/project/agent-lifecycle-kit/).
- One safe entrypoint: `agent-lifecycle start --adapter <adapter-id> --file task.md`.
- [Quickstart](guides/quickstart.md)
- [Project workflow profile](reference/project-workflow-profile.md)
- [Project workflow presets](reference/workflow-presets.md)
- [Effective configuration explanation](reference/effective-configuration.md)
- [Adapter action evidence](reference/adapter-action-evidence.md)
- [External verification checks](reference/external-verification-checks.md)
- [Bounded external tool jobs](reference/external-tool-jobs.md)
- [Optional security analysis profile](reference/security-analysis-profile.md)
- [Project principles and plan deltas](reference/project-principles-and-plan-deltas.md)
- [Project domain language and change impact](reference/project-domain-language.md)
- [Multi-run attention view](reference/multi-run-attention-view.md)
- [Long-term project governance](guides/long-term-project-governance.md)
- [Context checkpoints and compaction recovery](reference/context-checkpoints.md)
- [Release accounting](reference/release-accounting.md)
- [Workflow economics](reference/workflow-economics.md)
- [Phase-to-session handoff](guides/phase-session-handoff.md)
- [Phase packets](reference/phase-packets.md)
- [Validation ladder](reference/validation-ladder.md)
- [Structured result qualification](reference/structured-result-qualification.md)
- [Optional adapter lifecycle control](adapters/lifecycle-control.md)
- [How ALK works for different tasks](guides/how-alk-works.md)
- [Workflow customization and execution controls](reference/workflow-customization.md)
- [Plan verification and integrity](reference/plan-verification.md)
- [Evidence-based audit optimization](reference/audit-optimization.md)
- [Quality and cost learning](reference/quality-cost-learning.md)
- [Performance and resource budgets](reference/performance-and-resource-budgets.md)
- [Research evidence workflow](guides/research-workflow.md)
- [Research evidence reference](reference/research-evidence.md)
- [Public locators and redaction](reference/public-locators-and-redaction.md)
- [Finding-to-check adoption](reference/finding-check-adoption.md)
- [Lifecycle task scenarios](guides/lifecycle-cookbook.md)
- [Workflow continuation](reference/workflow-continuation.md)
- [System architecture](architecture/system-architecture.md)
- Architecture boundaries are enforced by the acyclic module/package policy in
  `policy/architecture-dependencies.json`; adapter inspection uses bounded
  literal-only `inspection_profile.py` files.
- [Project comparison](reference/project-comparison.md)
- [Planning-only adapter launch](reference/planning-only-launch.md)
- [Frozen-task launch through a verified profile](reference/qualified-host-launch.md)
- [Python quality and contribution checks](guides/contributing-and-quality.md)
- [CLI error contract](reference/cli-errors.md)
- [Supported Python API](reference/python-api.md)

## English documentation

- [Adapter support matrix](adapters/support-matrix.md)
- [Adapter progress bridge matrix](adapters/progress-bridge-matrix.md)
- [Adapter event capture matrix](adapters/event-capture-matrix.md)
- [Managed adapter session support](adapters/managed-session-support.md)
- [Adapter install](adapters/install.md)
- [Using ALK with an adapter](adapters/usage-modes.md)
- [Adapter live-promotion runbook](adapters/live-promotion-runbook.md)
- [Codex adapter](adapters/codex.md)
- [Claude Code adapter](adapters/claude.md)
- [Cursor adapter](adapters/cursor.md)
- [Gemini CLI adapter](adapters/gemini-cli.md)
- [Goose adapter](adapters/goose.md)
- [Grok Build adapter](adapters/grok-build.md)
- [Hermes adapter](adapters/hermes.md)
- [Kimi Code adapter](adapters/kimi-code.md)
- [OpenCode adapter](adapters/opencode.md)
- [OpenInterpreter adapter](adapters/openinterpreter.md)
- [Pi adapter](adapters/pi.md)
- [Qwen Code adapter](adapters/qwen-code.md)
- [Quickstart](guides/quickstart.md)
- [Beginner and advanced workflows](guides/beginner-and-advanced-workflows.md)
- [How ALK works for different tasks](guides/how-alk-works.md)
- [Lifecycle task scenarios](guides/lifecycle-cookbook.md)
- [Workflow continuation](reference/workflow-continuation.md)
- [Code review workflows](guides/code-review-workflows.md)
- [Multi-model review workflow](guides/review-mesh-workflow.md)
- [Issue to specification drafts](guides/issue-to-spec.md)
- [Offline source-release checks](guides/release-candidate.md)
- [Verified-adapter release checklist](guides/verified-adapter-release-checklist.md)
- [Production resource and security guide](guides/production-resource-security.md)
- [Reference task evaluation guide](guides/reference-task-evaluation.md)
- [External model harness evaluation](guides/model-harness-evaluation.md)
- [Execution-setup validation with reference tasks](reference/benchmark-qualification.md)
- [Research workflow](guides/research-workflow.md)
- [System architecture](architecture/system-architecture.md)
- [Workflow customization and execution controls](reference/workflow-customization.md)
- [Release architecture](architecture/release-architecture.md)
- [Runner transition contract](architecture/runner-transition-contract.md)
- [Runner extension map](architecture/runner-extension-map.md)
- [CLI reference](reference/cli.md)
- [Research evidence reference](reference/research-evidence.md)
- [Source of truth](reference/source-of-truth.md)
- [Project comparison](reference/project-comparison.md)
- [Plugin publication](reference/plugin-publication.md)
- [Portable Agent Plugins package](reference/agent-plugins.md)
- [Agent Plugins client qualification](reference/agent-plugin-qualification.md)
- [Completion check](reference/completion-check.md)
- [Goal continuity](reference/goal-continuity.md)
- [Follow-up register](reference/follow-up-register.md)
- [Worktree isolation receipts](reference/worktree-isolation.md)
- [Sandbox boundaries](reference/sandbox-boundaries.md)
- [Host capabilities](reference/host-capabilities.md)
- [Runner recovery receipts](reference/runner-recovery.md)
- [Managed lifecycle runner](reference/managed-lifecycle-runner.md)
- [Managed adapter sessions](reference/managed-adapter-sessions.md)
- [Optional thread bridge](reference/optional-thread-bridge.md)
- [Implementation audit](reference/implementation-audit.md)
- [Plan completeness](reference/plan-completeness.md)
- [Adapter event capture](reference/adapter-event-capture.md)
- [Review verdicts](reference/review-verdict.md)
- [Optional quality packs](reference/optional-quality-packs.md)
- [Optional cross-check profile](reference/cross-check-profile.md)
- [Review Mesh](reference/review-mesh.md)
- [Review efficiency](reference/review-efficiency.md)
- [Evidence independence](reference/evidence-independence.md)
- [Risk-bound independent verification](reference/risk-bound-independent-verification.md)
- [Review Mesh recommendation](reference/review-mesh.md#recommendation-advisor)
- [Review Mesh prepare](reference/review-mesh.md#operator-templates-and-prepare)
- [Review Mesh assignments and quorum](reference/review-mesh.md#assignments-results-synthesis-and-quorum)
- [Bug Forensics profile](reference/bug-forensics.md)
- [Bug Forensics context budget](reference/bug-forensics-context-budget.md)
- [Task templates](../templates/tasks/README.md)
- [Diagnostic bundles](reference/diagnostic-bundles.md)
- [Read-only status views](reference/read-only-status-view.md)
- [Adapter progress bridge](reference/automatic-progress-bridge.md)
- [Small-model packets](reference/small-model-packets.md)
- [Quality-preserving execution strategy](reference/execution-strategy.md)
- [Controlled runner](reference/runner.md)
- [Public contracts](reference/public-contracts.md)
- [Model routing](reference/model-routing.md)
- [Adaptive lifecycle policy](reference/adaptive-lifecycle-policy.md)
- [Quality-cost learning](reference/quality-cost-learning.md)
- [Reference task evaluation](reference/reference-task-evaluation.md)
- [Execution-setup validation with reference tasks](reference/benchmark-qualification.md)
- [Lifecycle cost accounting](reference/lifecycle-cost.md)
- [Usage export](reference/usage-export.md)
- [Process execution observability](reference/process-execution-observability.md)
- [Host-local token accounting](reference/host-local-token-accounting.md)
- [Neutrality scanning](reference/neutrality.md)
- [Evidence integrity](reference/evidence-integrity.md)
- [Import mappers](reference/import-mappers.md)
- [Episode retrieval](reference/episode-retrieval.md)
- [Lifecycle policy proposals](reference/policy.md)
- [Plan continuity](reference/plan-continuity.md)
- [Evidence index and imports](reference/evidence-imports.md)
- [Readiness diagnostics](reference/readiness-diagnostics.md)
- [Production promotion contract](reference/production-promotion.md)
- [Live cost calibration](reference/live-cost-calibration.md)
- [Release security](security/release-security.md)
- [Neutrality authority contract](security/neutrality-contract.md)

- [30-day raw retention and hourly maintenance](operations/retention-maintenance.md)


## Safe artifact helpers in 2.19

- [Create and inspect artifacts; prepare a freeze candidate](reference/safe-artifact-authoring.md).
- [Bounded reviewer input and raw response contracts](reference/review-mesh.md#bounded-review-handoff).
- [ALK, host, model and SDLC guarantees](architecture/sdlc-boundary.md).

## Composed workflow in 2.20

Use [workflow init --manifest](reference/cli.md#release-220-composed-initialization-and-digest-display)
for read-only actual-target projection; apply requires its full target digest and
a reviewed frozen plan. Execution authorization remains separate.
[Local-only continuation](reference/workflow-continuation.md) stops before workers,
reviews and authorization; ambiguous next actions require explicit input.
Status can show collision-safe prefixes alongside full identities. The measured
CLI trace uses 2 facade calls instead of 3 with identical state/events, but takes
longer in the small fixture. Snapshot fixtures use 6 Git children for 2/20/60 files
versus 10/64/184 in 2.19. Event validation still scans the complete log.

- [Source-native command accounting, bounded preparation and response recovery in 2.21](reference/source-native-workflow-accounting.md).

- [Conservative plan-review reuse in 2.22](reference/conservative-delta-review.md).

## Compact S0/S1 packages in 2.23

[Compact DRAFT authoring](reference/tier-proportional-plan-packages.md) preserves checks, independent review and separate authorization. Explicit acceptance-criteria.md and planFiles completion are required before freeze; UNKNOWN metrics are never zero.

## Release 2.26: bounded discovery and precise quality gates

Markdown imports bound examined entries, directories, depth and cooperative
elapsed time; see the [security control map](security/release-security.md). Tracked-source checks
reuse the existing bare-token families. [Quality controls](architecture/system-architecture.md)
require both combined and statement coverage of 76 percent and retain legacy
policy interpretation. The existing [reading pilot](guides/controlled-technical-english.md) and host limits
remain; measurements do not establish token savings or host enforcement.
