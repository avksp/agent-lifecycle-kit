# CLI reference

## Lifecycle command authority

Use `workflow run` and the `workflow task-*` commands for all integrations.
The former controlled-runner command surface is removed in 2.0. Historical
runner artifacts are handled only by the explicit read-only
`workflow migrate-runner-artifact` command described in
[Runner migration](../guides/runner-migration-2.md). A converted record is evidence only
and cannot mutate workflow state or satisfy acceptance/finalization.

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
  python -m pip install agent-lifecycle-kit==2.10.0
```

## Task evidence identity

Authoritative `workflow task-result`, `task-accept`, `task-rework` and
`task-review-apply` routes fail closed unless the result declares non-empty
`actor` and `actorRunId` values and the review declares a non-empty `reviewId`.
The reviewer id and reviewer run id must remain distinct from the worker
identity. Invalid evidence returns a typed `task-result-invalid`,
`task-review-invalid` or `task-review-self-certification` error before workflow
state or event-log bytes change. Historical evidence remains readable but
cannot bypass current acceptance.

## Error and resource contracts

The root CLI returns `agent-lifecycle-error.v1` with exit code `2` for expected
I/O, decoding, JSON-depth and unexpected failures. The JSON is redacted and
does not contain a traceback or local absolute path. Library exceptions and
`KeyboardInterrupt`/`SystemExit` behavior are unchanged. See the [CLI error
contract](cli-errors.md).

## Public locators and redaction

Evidence URLs use the offline `agent-public-evidence-locator.v1` contract.
Only HTTP(S) is accepted; hosts are normalized and credentials, unsafe schemes,
secrets and local paths are rejected or redacted. See [Public locators and
redaction](public-locators-and-redaction.md).

Built-in profiles are loaded through `importlib.resources`, so commands work
from an installed wheel outside the checkout. A same-named file in the current
directory cannot shadow a built-in profile; an explicitly supplied path still
takes precedence. The supported import surface is listed in the [Python API
reference](python-api.md).

## External verification checks

Use the optional project-owned checks to record bounded architecture or
dependency evidence:

```bash
agent-lifecycle quality external-check \
  --check-id import-boundaries \
  --plan-digest <64-hex-digest> \
  --plan-lock-digest <64-hex-digest> \
  --operation-id external-check-001 \
  --out work/external-check.json
```

The available built-in profiles are `import-boundaries`,
`module-dependencies` and `declared-dependencies`. Install the selected
analyzer in the project; ALK does not add it as a runtime dependency. Results
are source-, configuration- and plan-bound, raw output is not retained, and a
missing or incomplete analyzer returns `UNAVAILABLE`. The result has no
authority to accept, freeze or promote anything. See [External verification
checks](external-verification-checks.md).

## Bounded external tool jobs

Use `adapter external-job` only for optional adapter-owned work that needs an
addressable attempt, bounded cancellation or digest-only artifacts:

```bash
agent-lifecycle adapter external-job run --request job-request.json --out work/job.json -- <argv...>
agent-lifecycle adapter external-job status --request job-request.json --out work/job-status.json
agent-lifecycle adapter external-job cancel --request job-request.json --out work/job-cancel.json
```

Attempts use private create-only state under `.alk/external-jobs` by default.
Timeout, cancellation, failed cleanup, live children, post-terminal writes,
`NO_FINAL_VERDICT` and exceeded limits have no acceptance effect. ALK adds no
provider client, network call, daemon or workflow authority. See [Bounded
external tool jobs](external-tool-jobs.md).

## Optional security analysis

The security profile is disabled by default and keeps imported findings
untrusted:

```bash
agent-lifecycle quality security-profile --out work/security-profile.json
agent-lifecycle import security-findings \
  --source findings.sarif \
  --expected-source-revision <revision> \
  --out work/security-findings.json
agent-lifecycle quality security-finding-check \
  --candidate work/security-findings.json \
  --expected-source-revision <revision> \
  --out work/security-findings-validation.json
```

Use `report security-analysis --finding <path> --profile` for a bounded
read-only report. An imported finding or profile cannot start execution. A
high-severity remediation requires a fresh independent verification assignment
at task acceptance; implementer-only evidence is rejected with
`security-analysis-verification-required`. See [Optional security analysis
profile](security-analysis-profile.md).

## Performance and resource evidence

Release 1.78 keeps `version` lightweight through lazy command-family imports.
The performance harness and its hard ceilings are documented in [performance
and resource budgets](performance-and-resource-budgets.md). Timing is advisory
unless a plan says otherwise; security, compatibility, resource and
fail-closed checks remain mandatory.

`agent-lifecycle metrics phase-resources --input <path> --out <path>` converts
an explicit `agent-phase-resource-input.v1` into a bounded
`agent-phase-resource-measurement.v1`. `agent-lifecycle metrics
release-accounting --release-id <id> --artifact <path> --project-root <path>
--out <path>` composes unique local measurements into
`agent-release-accounting.v1`. Both routes use create-only output and make no
model, network or host-process call. Missing telemetry remains `UNAVAILABLE`
with a null value; `elapsedWallMs` and `computeMs` are never conflated. See
[release accounting](release-accounting.md).

## Optional adapter lifecycle control

`agent-lifecycle adapter lifecycle-control-check` validates the optional local
policy or supplied lifecycle-control request, decision, events and attestation
without starting a host. `agent-lifecycle adapter event-check` validates a
portable event stream. These commands return evidence for review; they do not
promote an adapter or edit host settings.

The operation-level fields are `declaredLevel`, `supportedLevel`,
`qualifiedLevel` and `qualificationStatus`. The bundled adapters currently
publish `GUIDANCE_ONLY` and `NO_RECOMMENDATION`, while managed launch remains
`WRAPPER_ONLY`. See [Optional adapter lifecycle control](../adapters/lifecycle-control.md).

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
- `agent-lifecycle plan lock-create --manifest <path> --review <path>
  [--repository-root <path>]`: validate the reviewed final package and create
  its canonical `agent-plan-lock.v2`. The command writes only after all package
  checks pass and fails rather than replacing an existing `plan.lock.json`.
- `agent-lifecycle plan verify`: compose a read-only verification receipt for a
  plan package, including manifest, traceability, lock and package integrity.
  It does not execute the plan's validation commands or authorize changes.
- `agent-lifecycle plan completeness-check`: return
  `agent-plan-completeness-validation.v1` with actionable tier blockers.
- `agent-lifecycle plan snapshot/reconcile/handoff`: maintain compact,
  reviewable plan state.
- `agent-lifecycle plan finding-check propose|validate|accept|evidence|transition`:
  bind an accepted finding to an existing deterministic check. Proposals remain
  advisory, check identities contain no executable command text, and evidence
  records read-only execution boundaries. See [Finding-to-check adoption](finding-check-adoption.md).
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

For a reviewer handoff, use `plan verify` with the manifest, package root,
acceptance checklist, lock and workflow state. See [Plan verification and
integrity](plan-verification.md) for the exact command and failure rules.

## Project profile

- `agent-lifecycle project profile init --adapter <adapter-id> --out .alk/project-profile.json`:
  create the minimal local defaults file and optionally set its default adapter.
  Omit `--adapter` when the value will be edited in the file or supplied per run.
- `agent-lifecycle project profile check`: validate and resolve the discovered
  `.alk/project-profile.json`.
- `agent-lifecycle project profile check --manifest <plan> --lock <lock>`:
  bind the profile to plan authority and emit the effective profile. Add
  `--adapter`, `--mode` or `--risk` for a safe one-command override.
- `agent-lifecycle project profile explain --profile <profile> --preset <id>
  --manifest <plan> --lock <lock> --descriptor <descriptor>
  --capability-manifest <manifest>`: return the read-only
  `agent-effective-configuration-explanation.v1` with field provenance,
  frozen-plan constraints and operation-specific enforceability. Add bounded
  `--adapter`, `--mode`, `--risk`, `--stage-risk` or `--stage-mode` overrides.
  Missing or stale capability lineage returns `UNAVAILABLE` and never promotes
  a claim. See [Effective configuration explanation](effective-configuration.md).
- `agent-lifecycle start --file <path>` or `--text <text>`: use the discovered
  profile when it supplies a default adapter. `--project-profile <path>` selects
  a contained profile explicitly; `--no-project-profile` disables discovery.

The profile is a project-local defaults layer. A frozen plan and matching lock
remain authoritative for risk, quality, write scope, gates and receipts. See
[Project workflow profile](project-workflow-profile.md).

## Workflow presets

Use the built-in workflow presets as bounded defaults for a common route:

```bash
agent-lifecycle project preset list
agent-lifecycle project preset inspect --preset feature-implementation
agent-lifecycle project preset validate --preset feature-implementation
agent-lifecycle project preset render \
  --preset research-review \
  --adapter <adapter-id> \
  --out .alk/project-profile.json
```

`project preset` commands read local versioned data, return stable JSON and do
not call a model or start a host. `render` writes only to the explicit output
path and never overwrites an existing file. For a one-off task, use
`start --preset <preset-id>` without creating a profile. Preset values are
defaults below explicit command-line and project-profile values; a frozen plan
can raise requirements but a preset cannot lower them. See [Workflow
presets](workflow-presets.md).

Check a project-principles artifact with
`agent-lifecycle project principles check --file <path>`. Compare two plan
revisions with `agent-lifecycle plan delta --before <manifest> --after
<manifest>` and validate the resulting report with `agent-lifecycle plan
delta-check --delta <delta.json>`. Both paths are read-only and return stable
JSON contracts.

## Project domain language

The optional vocabulary is checked with
`agent-lifecycle project language check --file <path> --project-root .` and
audited without edits with
`agent-lifecycle project language audit --file <path> --term-id <id>
--changed-path <path>`. Add both `--language-before <path>` and
`--language-after <path>` to `plan delta` to bind terminology changes to the
plan comparison. The vocabulary is read-only context; it cannot grant write
authority or replace the specification and frozen plan. See [Project domain
language](project-domain-language.md).

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
- `agent-lifecycle workflow continue`: project the next existing workflow
  transition without mutation by default. Repeat the same inputs with `--apply`,
  the projected state revision and action digest to invoke exactly that
  transition. For a declared deterministic sequence, add `--until-blocked`,
  `--apply`, an input bundle, explicit positive caps, a lock and an output
  receipt; batch mode stops before external authority. See
  [Workflow continuation](workflow-continuation.md).
- `agent-lifecycle workflow init --state <path> --run-id <id> --package-id
  <id>`: create one private, unbound `agent-workflow-state.v4` file without
  replacing an existing state.
- `agent-lifecycle workflow state-migrate --state <path> --operation-id <id>
  --expected-revision <n> --source-revision <sha>`: perform one explicit,
  fail-closed v3-to-v4 migration.
- `agent-lifecycle workflow authorize`: consume one unexpired,
  exact-lineage authorization receipt and move an approval-required run from
  `AWAITING_AUTHORIZATION` to `READY`. It is rejected for `PLAN_ONLY`.
- `agent-lifecycle workflow external-pause` and `external-resume`: pause a
  supported execution or final-audit phase for one declared host-owned action,
  then resume only after the matching receipt is present. Both operations bind
  run, plan and source lineage and use the normal revision/idempotency checks.
- `agent-lifecycle workflow task-start`: open a bounded task attempt.
- `agent-lifecycle workflow task-snapshot`: compute the current task-scoped
  Git file set and content digests without changing workflow state. Put the
  returned `claim` object in the task result before `task-result`.
- `agent-lifecycle workflow task-result`: submit implementation evidence.
- `agent-lifecycle workflow task-rework`: after an independent review or
  implementation audit returns `REWORK`, archive the current attempt and move
  the task to `REMEDIATING`. Repeat `--finding-id` for each open finding being
  addressed. The frozen plan must enable remediation and allow another attempt.
- `agent-lifecycle workflow task-accept`: accept a completed task. Add
  `--implementation-audit <implementation-audit.json>` when the plan or task
  requires accepted implementation audit evidence.
- `agent-lifecycle workflow task-review-apply`: apply one independently
  reviewed task outcome. It is the canonical route for `ACCEPTED`, `REWORK`,
  `CONTRACT_CHANGE` and `BLOCKED`; repeat `--finding-id` for the open findings
  of a `REWORK` decision.
- `agent-lifecycle workflow final-audit-outcome`: apply an independent final
  audit verdict. `ACCEPTED` permits finalization; `REWORK` archives only the
  named accepted tasks and opens bounded remediation; `CONTRACT_CHANGE` waits
  for a new frozen plan; `BLOCKED` waits for the declared external action.
  No verdict edits the plan or bypasses the retry and ownership boundaries.
- `agent-lifecycle workflow block/resolve-blocker`: record external blockers.
- `agent-lifecycle workflow finalize`: produce final lifecycle proof. Add
  `--proof-integrity <receipt.json>` when the run or final audit requires
  proof-integrity evidence, and `--completion-gate-receipt <receipt.json>` when
  completion gate binding is required. Add
  `--final-implementation-audit <final-implementation-audit.json>` when final
  implementation audit is mandatory, and `--review-mesh-quorum <path>` when an
  opted-in plan requires final-audit quorum.
- `workflow run`, `workflow task-result`, `workflow task-accept`,
  `workflow task-review-apply`, `workflow final-audit-outcome` and
  `workflow finalize` are the only workflow commands with managed progress
  hooks in this release. `ALK_PROGRESS_HOOK=stderr` is supported for wrappers;
  plugin installation alone is not lifecycle proof.
- `agent-lifecycle workflow run`: execute the current workflow route with
  frozen plan and state lineage.
- `agent-lifecycle workflow migrate-runner-artifact`: convert one bounded
  historical runner artifact to a private, read-only, non-authoritative record.
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
- `agent-lifecycle benchmark sample`: create a deterministic bounded sample by
  task family, tier and shape.
- `agent-lifecycle benchmark receipt-check --receipt ...`: validate an
  externally produced execution record without starting its runner. The
  technical schema keeps `receipt` for compatibility.
- `agent-lifecycle benchmark qualify --receipt ...`: apply minimum task, repeat,
  stratum and quality-evidence thresholds to one route.
- `agent-lifecycle benchmark compare-routes --baseline ... --candidate ...`:
  compare execution setups that meet the minimum evidence requirements while
  keeping environment and scorer changes explicit.

Structured-result capability qualification is documented in [Structured result
qualification](structured-result-qualification.md). It uses the existing
benchmark receipts and Python contract helpers; Release 1.89 does not add a
provider-specific response-format command. Qualification remains advisory and
cannot accept a workflow task or promote an adapter.

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
  cost report from explicit JSON artifact paths. Phase-resource inputs use
  their declared token and step totals rather than a JSON-size estimate.
- `agent-lifecycle metrics phase-resources --input <path> --out <path>`:
  validate and persist a bounded phase measurement without replacing an
  existing artifact.
- `agent-lifecycle metrics release-accounting --release-id <id> --artifact
  <path> --project-root <path> --out <path>`: aggregate up to 64 unique local
  source artifacts into fixed ALK-process, implementation, audit and
  post-audit-remediation views. Repeat `--artifact`; add `--provenance` to
  compare declared and observed identities without claiming attestation.
- `agent-lifecycle metrics usage-export`: export sessions, receipt digests,
  tokens, resources, durations, budget decisions, and optional host-reported
  `cost_usd` from explicit JSON artifact paths.
- `agent-lifecycle metrics execution-report --receipt <path> --out <path>`:
  aggregate redacted process-execution receipts into a local resource report.
  Repeat `--receipt` for several invocations; add `--operation-id` to bind the
  report to one operation.
- `agent-lifecycle metrics recommend`: suggest the lightest lifecycle mode that
  preserves the required quality floor.
- `agent-lifecycle metrics outcome-index/quality-signals/learn-recommend`:
  derive advisory local learning signals from explicit lifecycle receipts.
- `agent-lifecycle metrics audit-sample --receipt <path> --out <path>`:
  build a bounded sample batch from review, usage and process receipts.
- `agent-lifecycle metrics audit-report --sample <path> --candidate-profile <path> --out <path>`:
  calculate quality, time, token and resource statistics, evaluate holdout
  tasks and produce an advisory profile recommendation. Add `--terminal` for
  a compact operator view.
- `agent-lifecycle metrics audit-efficiency --input <path> --comparison <path> --out <path>`:
  validate explicit lineage-bound accounting inputs and write advisory
  quality-preserving efficiency metrics. Repeat `--comparison`; one sample
  returns `NO_COMPARISON`, and `UNAVAILABLE` never becomes zero.
- `agent-lifecycle metrics audit-proposal --report <path> --out <path>`:
  record an explicit approval decision for a recommendation. Use
  `--approved` only after reviewing the report; it never edits a frozen plan.
- `agent-lifecycle metrics audit-apply --proposal <path> --out <path>`:
  write a new approved profile artifact. Plan manifests and lock files are
  rejected as output targets.

For the complete evidence, holdout and approval flow, see [Evidence-based audit
optimization](audit-optimization.md).
For provenance, sample adequacy and measured audit-use semantics, see
[evidence independence](evidence-independence.md) and
[review efficiency](review-efficiency.md).
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

## Research evidence

- `agent-lifecycle research validate --package <path> [--snapshot SOURCE_ID=PATH] --out <path>`:
  validate a local `agent-research-evidence-package.v1`, bind citations to
  explicit UTF-8 snapshots when supplied, inspect provenance and write a
  fail-closed validation receipt.
- `agent-lifecycle research summary --package <path> --validation <path> --out <path>`:
  create a bounded summary with supported claims, evidence gaps, duplicate
  groups and lifecycle counts.

Research commands read only explicit local paths. They do not fetch URLs, call
models or launch host processes. A research summary is planning input, not a
specification, frozen plan or acceptance decision. See [research evidence](research-evidence.md)
and the [research workflow](../guides/research-workflow.md).

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
- `agent-lifecycle report status-view/event-feed/multi-run/progress/change-summary`:
  render read-only status, workflow events, a bounded multi-run attention view,
  lifecycle progress and Git-style change summary receipts. Multi-run reads
  only explicit run roots and reports overlaps without changing authority.
  Progress supports bounded `--watch` and explicit `--terminal` text output.
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
