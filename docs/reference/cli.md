# CLI reference

The CLI prints JSON for machine-readable commands. Commands that mutate state
record receipts or require explicit input files; diagnostic commands stay
read-only unless their own help says otherwise.

For the choice between the simple `start` route and the atomic lifecycle
commands, including multiple agents, host model settings, prompts, timeouts
and retries, see [Workflow customization and execution
controls](workflow-customization.md).

For a first installation and the shortest task route, use [Install ALK and make
the first run](../guides/install-and-first-run.md). The task-oriented command
map is in [Commands by task](../guides/commands-by-task.md).

## Installation

Python 3.11-3.14 is supported. Install the exact release from the official
[PyPI project](https://pypi.org/project/agent-lifecycle-kit/):

```bash
  python -m pip install agent-lifecycle-kit==1.68.0
```

## Foundation

- `agent-lifecycle version`: print package version.
- `agent-lifecycle schema list`: list known public schemas.
- `agent-lifecycle schema show <schema-id>`: print one schema.
- `agent-lifecycle contract policy/check`: inspect public compatibility policy.
- `agent-lifecycle tier resolve --request <request.json>`: resolve the SDD tier
  and deterministic request digest from a structured tier request.
- `agent-lifecycle conformance`: reserved compatibility selector. It has no
  executable conformance workflow; use `agent-lifecycle adapter validate`,
  adapter inspection and the release conformance validators instead.

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
  reviewed. `import plan --source <file-or-folder> --dialect
  openspec|spec-kit|bmad|spec-kitty` imports OpenSpec, Spec Kit, BMAD or Spec
  Kitty Markdown planning material with deterministic provenance.
- `issue-to-spec` skill: convert external issues into draft-only ALK
  specification input.
- `agent-lifecycle quality template-list/template-check`: inspect and validate
  draft-only task templates.
- Task scenario entry points for common tasks are documented in
  `docs/guides/lifecycle-cookbook.md`.

## Project profile

- `agent-lifecycle project profile init --adapter <adapter-id> --out .alk/project-profile.json`:
  create the minimal local defaults file and optionally set its default adapter.
  Omit `--adapter` when the value will be edited in the file or supplied per run.
- `agent-lifecycle project profile check`: validate and resolve the discovered
  `.alk/project-profile.json`.
- `agent-lifecycle project profile check --manifest <plan> --lock <lock>`:
  bind the profile to plan authority and emit the effective profile. Add
  `--adapter`, `--mode` or `--risk` for a safe one-command override.
- `agent-lifecycle start --file <path>` or `--text <text>`: use the discovered
  profile when it supplies a default adapter. `--project-profile <path>` selects
  a contained profile explicitly; `--no-project-profile` disables discovery.

The profile is a project-local defaults layer. A frozen plan and matching lock
remain authoritative for risk, quality, write scope, gates and receipts. See
[Project workflow profile](project-workflow-profile.md).

## Execution

- `agent-lifecycle start --adapter <id> (--file task.md | --text "..." |
  --resume <session-id>)`: beginner-facing facade over task intake, frozen
  managed-run delegation and stored ALK session resume. Task-source aliases are
  `--task-file` and `--task-text`; exactly one action is required.
  `--mode auto|research|plan|review|implement` defaults to `auto`. Raw input and
  every mode except explicit `implement` remain non-executing. `implement`
  requires a structured frozen request with complete state, manifest, lock,
  task, operation and revision bindings. The command returns
  `agent-lifecycle-start-receipt.v1` and never treats `--resume` as a native
  host conversation identifier. External execution remains off unless a fully
  bound `implement` call also supplies `--launch --host-launch-profile
  .alk/host-launch/<adapter>.json`; see [Local host
  launch](local-host-launch.md).
- `agent-lifecycle start --adapter <id> --mode plan --file task.md --launch`:
  request one exact-version qualified planning-only host process. The outer
  start receipt remains `DRAFT_PLAN_REVIEW`; the nested planning receipt records
  host/model start and can only end at review or block. Current shipped
  candidates are `PLANNING_ONLY_UNSUPPORTED`, so this route fails closed until
  live qualification. See [Planning-only adapter
  launch](planning-only-launch.md).
- `agent-lifecycle host-launch inspect/preflight --profile <path>`: validate an
  ignored operator-local profile with zero process calls, or explicitly make
  one bounded version probe. These commands do not authorize task execution.

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
  implementation audit is mandatory, and `--review-mesh-quorum <path>` when an
  opted-in plan requires final-audit quorum.
- `workflow run`, `workflow task-result`, `workflow task-accept` and
  `workflow finalize` are the only workflow commands with managed progress
  hooks in this release. `ALK_PROGRESS_HOOK=stderr` is supported for wrappers;
  plugin installation alone is not lifecycle proof.
- `agent-lifecycle runner start/status/transition/stop/resume`: control
  bounded execution state.
- `agent-lifecycle strategy resolve --manifest ... --lock ... --state ...
  --task ... --operation-id ... --expected-revision ... --source-revision ...
  --adapter ... --out ...`: write one provider-neutral, read-only execution
  strategy. S1/S2 also require a matching `--host-model-profile`.
- `agent-lifecycle task compile --manifest ... --strategy ...`: project a
  validated strategy into the matching full task packet without changing plan
  authority.
- `agent-lifecycle task compile-small`: compile frozen task packets into
  small-model packets with output contracts and compact context receipts. Add
  `--strategy` to require an eligible `COMPACT` strategy.

## Review and quality

- `agent-lifecycle benchmark evaluate`: compare an explicit submission with the
  bundled deterministic reference-task suite and emit
  `agent-reference-task-evaluation.v1` without model or host calls.
- `agent-lifecycle benchmark compare --baseline ... --candidate ...`: compare
  two evaluation receipts quality-first and report confidence-aware token,
  invocation, retry, remediation and elapsed-time deltas.
- `agent-lifecycle audit review-check`: validate review verdicts.
- `agent-lifecycle audit implementation`: emit
  `agent-implementation-audit-report.v1` for a task result and independent
  review. Add `--review-mesh-quorum <path>` when an opted-in plan requires
  Review Mesh quorum for implementation audit.
- `agent-lifecycle audit final-implementation`: aggregate accepted
  implementation audit reports before final workflow proof.
- `agent-lifecycle audit package --plan-dir <dir>`: audit a plan directory and,
  when `--state <path>` is supplied, aggregate its implementation audit. Add
  `--require-frozen --require-implementation --strict` for a completed handoff
  gate; repeat `--report <path>` to provide an explicit report list.
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
- `agent-lifecycle review-mesh profile`: create
  `agent-review-mesh-profile.v1` from token/resource caps and provider-neutral
  reviewer model classes.
- `agent-lifecycle review-mesh recommend`: inspect task text, a task file, an
  adapter task intake receipt or a plan manifest and emit
  `agent-review-mesh-recommendation.v1`. The receipt is advisory only and does
  not create assignments, launch adapters or enable blocking gates.
- `agent-lifecycle review-mesh template-list/prepare`: inspect built-in
  operator templates and prepare a local profile plus assignment packets from
  an intake receipt, manifest or handoff. `prepare` writes
  `agent-review-mesh-prepare-receipt.v1` and does not call providers or launch
  reviewer CLIs.
- `agent-lifecycle review-mesh assign/import-result/synthesize/quorum`: create
  host-owned reviewer packets, import redacted reviewer output, synthesize
  findings and build a quorum receipt. These commands do not call models or
  launch host CLIs.

## Context and continuity

- `agent-lifecycle context check/render`: validate and render compact context.
- `agent-lifecycle context external-import`: import one local external memory or
  context file as `agent-external-context-import-receipt.v1` without network,
  model or provider calls.
- `agent-lifecycle context episode-retrieve`: build `agent-episode-retrieval.v1`
  from explicit artifacts and optional `--external-context` receipts.
- `agent-lifecycle context checkpoint`: write a bounded
  `agent-context-checkpoint.v1` from explicit session, state, plan and summary
  inputs.
- `agent-lifecycle context restore`: validate lineage and return an
  `agent-context-continuation.v1` packet after compaction; stale or tampered
  checkpoints are blocked and never grant implementation authority.
- `agent-lifecycle goal check/summarize/view/update`: keep user intent
  traceable. `goal view` combines the goal record with lifecycle progress,
  optional usage receipts and optional change summaries without mutating state.
- `agent-lifecycle followup check/add/close/sweep`: track deferred work.
- `agent-lifecycle worktree policy-check/receipt/check`: verify write-scope and
  attempt isolation.

## Adapters

Use `agent-lifecycle start` for the simple path. The commands below remain the
atomic interface for scripts and advanced operators.

- `agent-lifecycle adapter validate`: check a descriptor against the baseline.
- `agent-lifecycle adapter inspect`: inspect source projection and safe host
  command surfaces.
- `agent-lifecycle adapter plugin-qualify --adapter codex|claude|cursor
  --profile <path> --package <path> --project-root <path>`: run the explicit,
  bounded read-only Agent Plugins client probe and return a qualification
  receipt. Installation remains client-owned; `QUALIFIED` is not lifecycle or
  managed-launch proof.
- `agent-lifecycle adapter scaffold`: create an `EXPERIMENTAL` adapter
  skeleton.
- `agent-lifecycle adapter install-plan`: preview host setup without writes.
- `agent-lifecycle adapter launch-profile --adapter codex|claude|opencode
  --repository-root <ALK checkout> --out .alk/host-launch/<adapter>.json`:
  create a version-bound local profile without executing the host. Follow with
  `host-launch preflight`; see [Frozen-task launch through a verified
  profile](qualified-host-launch.md).
  The same file contains a planning candidate section, but version preflight
  alone does not change `PLANNING_ONLY_UNSUPPORTED` to qualified.
- `agent-lifecycle adapter event-check`: validate neutral adapter event
  streams.
- `agent-lifecycle adapter event-capture-check`: validate declared
  adapter-owned event capture with descriptor, optional capability manifest,
  stream and `agent-adapter-event-stream-receipt.v1`.
- `agent-lifecycle adapter thread-capability --descriptor <path> --manifest
  <path> [--receipt <path>]`: inspect one adapter's declared thread operations
  and project their effective status without contacting a host.
- `agent-lifecycle adapter thread-qualify --descriptor <path> --receipt
  <path> [--manifest <path>]`: validate an adapter-owned thread qualification
  receipt against descriptor and capability-manifest identities. The command
  returns a non-zero status when a declaration, receipt or binding is invalid.
- `agent-lifecycle adapter session start/status/resume/promote`: record and
  resume adapter sessions. Plain interactive sessions return
  `WAITING_FOR_TASK`; promoted sessions bind to workflow state and task lineage.
- `agent-lifecycle adapter session start --launch`: validates the requested
  launch profile, then returns `adapter-generic-launch-disabled` before process
  creation. A descriptor alone never authorizes a generic native host launch.
  Generic environment selection accepts exact allowlisted variable names only;
  wildcard patterns are rejected.
- `agent-lifecycle start --mode implement --launch --host-launch-profile
  <path>`: the only CLI route to operator-local native execution. It requires a
  frozen lock-bound run and derived risk profile; it does not promote the
  adapter beyond `WRAPPER_ONLY`.
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
  `agent-adapter-session-receipt.v1`. It does not bypass the generic launch
  block or start a native host process.

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
- `agent-lifecycle-neutrality scan --scope tracked-release --policy <file>`:
  scan Git-index-bound release content. `--include-local-artifacts` explicitly
  adds only policy-approved `localArtifactRoots`; legacy scopes remain accepted
  but are signed as deprecated. See [Neutrality scanning](neutrality.md).

Use `--help` on any command group for exact arguments.
