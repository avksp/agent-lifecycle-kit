# CLI reference

The CLI prints JSON for machine-readable commands. Commands that mutate state
record receipts or require explicit input files; diagnostic commands stay
read-only unless their own help says otherwise.

## Foundation

- `agent-lifecycle version`: print package version.
- `agent-lifecycle schema list`: list known public schemas.
- `agent-lifecycle schema show <schema-id>`: print one schema.
- `agent-lifecycle contract policy/check`: inspect public compatibility policy.

## Planning

- `agent-lifecycle specification check`: validate specification shape.
- `agent-lifecycle specification completion-gate`: build a deterministic
  stop/continue/escalate/split/follow-up receipt from current evidence.
- `agent-lifecycle plan check`: validate a plan manifest and optional lock. Add
  `--require-completeness` to enforce structural completeness for the selected
  SDD tier.
- `agent-lifecycle plan completeness-check`: return
  `agent-plan-completeness-validation.v1` with actionable tier blockers.
- `agent-lifecycle plan snapshot/reconcile/handoff`: maintain compact,
  reviewable plan state.
- `agent-lifecycle import plan/check`: keep imported work draft-only until
  reviewed.
- `issue-to-spec` skill: convert external issues into draft-only ALK
  specification input.
- `agent-lifecycle quality template-list/template-check`: inspect and validate
  draft-only task templates.

## Execution

- `agent-lifecycle workflow run`: verify the frozen plan/state binding and
  return the next host-owned action without mutating state or starting model
  work. Add `--progress-hook stderr` for opt-in terminal progress on stderr, or
  `--progress-hook receipt --progress-receipt <path>` to persist
  `agent-progress-hook-receipt.v1` while preserving JSON stdout.
- `agent-lifecycle workflow task-start`: open a bounded task attempt.
- `agent-lifecycle workflow task-result`: submit implementation evidence.
- `agent-lifecycle workflow task-accept`: accept a completed task. Add
  `--implementation-audit <implementation-audit.json>` when the plan or task
  requires accepted implementation audit evidence.
- `agent-lifecycle workflow block/resolve-blocker`: record external blockers.
- `agent-lifecycle workflow finalize`: produce final lifecycle proof. Add
  `--proof-integrity <receipt.json>` when the run or final audit requires
  proof-integrity evidence, and `--completion-gate-receipt <receipt.json>` when
  completion gate binding is required. Add
  `--final-implementation-audit <final-implementation-audit.json>` when final
  implementation audit is mandatory.
- `workflow run`, `workflow task-result`, `workflow task-accept` and
  `workflow finalize` are the only workflow commands with managed progress
  hooks in this release. `ALK_PROGRESS_HOOK=stderr` is supported for wrappers;
  plugin installation alone is not lifecycle proof.
- `agent-lifecycle runner start/status/transition/stop/resume`: control
  bounded execution state.
- `agent-lifecycle task compile-small`: compile frozen task packets into
  small-model packets with output contracts and compact context receipts.

## Review and quality

- `agent-lifecycle audit review-check`: validate review verdicts.
- `agent-lifecycle audit implementation`: emit
  `agent-implementation-audit-report.v1` for a task result and independent
  review.
- `agent-lifecycle audit final-implementation`: aggregate accepted
  implementation audit reports before final workflow proof.
- `agent-lifecycle quality pack-check`: validate optional quality packs.
- `agent-lifecycle quality behavior-check`: run fixture-backed behavior checks.
- `agent-lifecycle quality bug-recipe-list/bug-recipe-check`: inspect reusable
  Bug Forensics recipes that reuse existing receipts.
- `agent-lifecycle metrics cost-check`: validate lifecycle cost receipts.
- `agent-lifecycle metrics cost-report`: generate and validate a lifecycle
  cost report from explicit JSON artifact paths.
- `agent-lifecycle metrics usage-export`: export sessions, receipt digests,
  tokens, resources, durations, budget decisions, and optional host-reported
  `cost_usd` from explicit JSON artifact paths.
- `agent-lifecycle metrics recommend`: suggest the lightest lifecycle mode that
  preserves the required quality floor.
- `agent-lifecycle metrics outcome-index/quality-signals/learn-recommend`:
  derive advisory local learning signals from explicit lifecycle receipts.
- `agent-lifecycle policy tune`: build a read-only policy proposal or write an
  approved policy artifact with `--apply --output`.
- `agent-lifecycle policy adaptive-decision/adaptive-check`: build and validate
  neutral adaptive lifecycle mode decisions.
- `agent-lifecycle review-mesh recommend`: inspect task text, a task file, an
  adapter task intake receipt or a plan manifest and emit
  `agent-review-mesh-recommendation.v1`. The receipt is advisory only and does
  not create assignments, launch adapters or enable blocking gates.

## Context and continuity

- `agent-lifecycle context check/render`: validate and render compact context.
- `agent-lifecycle goal check/summarize/update`: keep user intent traceable.
- `agent-lifecycle followup check/add/close/sweep`: track deferred work.
- `agent-lifecycle worktree policy-check/receipt/check`: verify write-scope and
  attempt isolation.

## Adapters

- `agent-lifecycle adapter validate`: check a descriptor against the baseline.
- `agent-lifecycle adapter inspect`: inspect source projection and safe host
  command surfaces.
- `agent-lifecycle adapter scaffold`: create an `EXPERIMENTAL` adapter
  skeleton.
- `agent-lifecycle adapter install-plan`: preview host setup without writes.
- `agent-lifecycle adapter event-check`: validate event capture receipts.
- `agent-lifecycle adapter session start/status/resume/promote`: record and
  resume adapter sessions. Plain interactive sessions return
  `WAITING_FOR_TASK`; promoted sessions bind to workflow state and task lineage.
- `agent-lifecycle adapter task start --adapter <id> (--file task.md |
  --text "...")`: accept task input for a selected adapter. Raw text and
  Markdown produce `agent-adapter-task-start-receipt.v1` with
  `REVIEW_REQUIRED`; `--task-file` and `--task-text` are aliases. The receipt
  may include advisory `reviewMeshRecommendation` when extra reviewers may help,
  but it remains draft-only. Structured `agent-adapter-task-run-request.v1`
  files or frozen manifests with `--state`,
  `--lock`, `--task`, `--operation-id`, `--expected-revision` and
  `--source-revision` delegate to the managed run path.
- `agent-lifecycle adapter run`: bind an adapter session to a frozen workflow
  state and return an ALK-managed next action. Progress is shown on stderr by
  default for this managed path, while JSON stdout stays
  `agent-adapter-session-receipt.v1`.

## Diagnostics and evidence

- `agent-lifecycle diagnose`: build one redacted checkout readiness report.
- `agent-lifecycle diagnostics bundle`: collect selected evidence into a
  redacted bundle.
- `agent-lifecycle report status-view/event-feed/progress/change-summary`:
  render read-only status, workflow event, lifecycle progress and Git-style
  change summary receipts. Progress supports bounded `--watch` and explicit
  `--terminal` text output.
- `agent-lifecycle report progress-bridge`: build
  `agent-progress-bridge-receipt.v1` for adapter wrappers that need a stable
  JSON receipt and optional terminal text.
- `agent-lifecycle evidence index/search`: build and query compact evidence
  indexes.
- `agent-lifecycle model profile-check/route/usage-check`: validate routing and
  usage receipts.

Use `--help` on any command group for exact arguments.
