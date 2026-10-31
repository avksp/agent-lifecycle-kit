# CLI reference

## Release 2.35: external AI SDLC integration

External clients use the existing public CLI without a task-manager dependency.
Negotiate `agent-lifecycle version` and its `agent-lifecycle-version.v1` schema
against an explicit supported-version list before mutation; unknown contracts
refuse. Bind each request to the frozen manifest/lock, run/task, source revision,
operation identity, expected state revision and projected action digest.
`workflow continue` projects read-only; apply only that exact projection with
all required inputs. Native guards, independent review, attested usage and
critical model routing remain required. Missing input is not success. Local UI
flags and fixture attestations cannot replace native authority. After a lost
reply, inspect native state and reconcile the operation before deciding whether
to retry; arbitrary host commands have no exactly-once guarantee. Preserve prior
attempts, costs, original clocks and null/UNAVAILABLE provider telemetry.

The eight bounded consumer cases cover read-only projection, one guarded action,
stale revision/action refusal without writes, missing required input, refusal of
unattested usage, refusal of an unsuitable critical model route, reconciliation
after a lost reply without a second mutation, and consumer refusal of unknown
version/schema before mutation. Disposable fixture bootstrap is `UNIT_ONLY`;
installed CLI subprocesses use no source `PYTHONPATH`. These cases start no model
calls and establish neither live host qualification nor every CLI operation.

Wheel and sdist include the full EN/RU integration guides and the eight-case JSON.
Installation places them under `share/agent-lifecycle-kit/integration` below
`sysconfig.get_path("data")`; sdist retains their `docs/` and `tests/` source paths.
The portable plugin retains its 19-document layout
and ships this paired CLI contract. Full guides and their linked repository
references are also available in the intended immutable release source:
[English guide](https://github.com/avksp/agent-lifecycle-kit/blob/v2.35.0/docs/guides/ai-sdlc-integration.md),
[Russian guide](https://github.com/avksp/agent-lifecycle-kit/blob/v2.35.0/docs/ru/guides/ai-sdlc-integration.md),
and [case inventory](https://github.com/avksp/agent-lifecycle-kit/blob/v2.35.0/tests/cli/fixtures/external-consumer-cases.json).
These tag links become available after publication; they are not evidence that
publication has occurred. The Python package supplies the CLI; the plugin supplies
instructions and documents. No new runtime API, server or host capability is added.

The Windows baseline repairs retain bounded ownership checks and canonical
coordinator replacement. Full candidate platform CI remains required before task
acceptance. Final independent audit and native completion precede protected merge,
main CI, tag and public artifact verification; this documentation grants no gate.

## Release 2.34: Windows315 accounting Git backend

Normal repository CI selects the Git executable from its own verified exec-path
only for Windows/Python 3.15. The other 14 OS/Python cells keep the default route.
Normal package installations also keep the default route. The internal CI
`ALK_ACCOUNTING_GIT_EXECUTABLE` setting applies only to legacy declared-accounting
Git reads. It does not change PATH or other Git callers. Absolute-file checks,
timeouts, output bounds, worktree checks and error behavior remain required.
CI records wrapper/backend hashes and matching versions before the tests, then
checks both executable hashes and PATH again afterward.

One Windows Server 2025/Python 3.15.2 experiment used three alternating
baseline/candidate pairs. Each of its six full samples passed the original
78 tests with matching case IDs and events. Baseline median: 1238.329 seconds;
candidate median: 1033.815 seconds; reduction: 16.52%. Baseline median absolute
deviation: 4.666 seconds. The preliminary short profile improved by 16.67%.
These values describe that worker and workload. They do not promise a general
speed increase, a benefit on other Python versions, or whole-process-tree memory
measurements. The separate local full suite passed 4138 tests with 59 expected
platform/applicability skips. All 15 correctness cells and existing security,
architecture, quality and package checks remain required.

[Recorded experiment](https://github.com/avksp/agent-lifecycle-kit/actions/runs/41156920182):
source `3fb0587c0dd43dfd7a73d0e5bcd9820b4420191c`, baseline
`e6cd9a0f3524b55a9197bc543d629b6bc2ed3fd2`. Release accounting retains failed
attempts and unavailable telemetry. Missing model token or money data is not zero.

## Release 2.33: selected architecture and tooling quality

This release changes selected internal code and repository quality checks. The
public `host_bridge.decode_json_object` keeps the bounded decoder behavior;
its legacy `_json` name remains an alias. Closing policy uses the existing
public `closing_time.closing_instant` contract. No new wrapper layer is added.

The private-import allowance count falls from 83 to 81. One final-evidence
flow falls from 58 to 41 branches; its new pure helper has 17. The total runtime
branch score remains 29,348. The remaining 81 allowances and other complex
functions remain recorded debt. Error order and authority boundaries retain
their existing meaning.

The existing quality runner checks the documentation validator, its one
internal rules helper, and the Python-quality validator with selected Ruff,
format and strict mypy checks. Eleven observed strict-type findings are fixed.
The existing runtime baselines, coverage floors and toolchain pins are retained.
Two selected runtime contracts have strict checks; the two earlier contract
checks remain separate, with no duplicate strict path.

The documentation validator and helper contain 1,148 and 1,193 lines. Both
stay below the 1,200-line hard limit and above the 800-line warning. All 130
ordered documentation rules, their finding order and 15 EN/RU manual pairs are
retained. These are bounded code and guard changes, not removal of all debt.

Both installation manuals pin the Codex marketplace example to `v2.33.0`.
Publication validation rejects missing, stale or conflicting refs in these
examples. The plugin provides instructions and documents; CLI behavior still
requires the matching Python package.

The version-specific release-accounting fixture contains a partial cutoff of
actual identified command receipts and actor presence. Failed attempts and
original clocks are retained; actor presence is not a measured model-turn
count. Provider input, output, cached tokens and USD stay null/UNAVAILABLE.
The fixture does not prove whole-run billing or publication. These changes do
not add host enforcement, model capability or measured token/speed savings.

## Release 2.32: process observations and reading scope

Existing cost reports add `processObservation` from one shared calculation:
pipeline compliance plus coordination is process; implementation plus product
validation is useful work. Reported and confirmed subtotals are separate and
retain confidence and supplied-entry scope. `ATTESTED` entries alone do not
prove a complete host/run inventory. Without that inventory, whole-run shares
remain null/UNAVAILABLE. A process-dominance warning can accompany legacy PASS;
it does not change the pipeline verdict, limits, task acceptance or authority.
Source collection counts a canonical resolved file path once, including relative
and absolute aliases. Distinct paths remain distinct even for identical payloads.

The existing release-accounting command keeps four views and unavailable usage:

```bash
agent-lifecycle metrics release-accounting --release-id 2.32.0 \
  --artifact work/release-source.json --project-root . \
  --out work/release-accounting.json
```

Supply actual current-release evidence; the example path is an input placeholder.
A bounded source cutoff is partial accounting, not whole-run billing. Retain
failed/interrupted attempts, research, plugin maintenance and unknown model work.
Do not substitute UI goal counters or zeros for missing tokens, input/output,
cached input or USD. The command starts no live calls and grants no promotion.

Fifteen explicit EN/RU manual pairs have a finite contradiction guard and
independent semantic review. Thirteen fixed scenarios include twelve negative
cases and a positive control. The malicious-import case observes DRAFT,
`freezeBlocked` and refusal of authority mutation. These checks establish the
selected cases; they do not prove arbitrary model behavior or host enforcement.

Eight selected stage-reading cases include separate S0/S2 plan-authoring intents.
The complete seven role contracts and routers are unchanged. Against exact 2.31
source, plan authoring changes 25,643 → 23,570 UTF-8 bytes, defect repair
26,247 → 24,174, plan review 30,550 → 28,477 and implementation audit
29,220 → 27,147. Compilation stays 9,665 and intake 9,280; S0 and S2 authoring
each change 25,643 → 23,570. The plan/defect reductions are 8.084%/7.898%, below
the 10% engineering target; the strict-decrease criterion is met. Counts include
mandatory shared/transitive reading and are source projections, not full host
input, tokens or model savings. Provider usage and such savings are UNAVAILABLE.
The existing fixed local batch comparison uses two explicit CLI/facade calls
versus one batch call with byte-identical state/events and no host launch. It can
be slower and establishes no provider-call reduction or general speedup.

Role/risk/context/qualification guidance uses existing provider-neutral profiles.
It adds no runtime selector, gate, host enforcement or automatic cloud fallback.
Mandatory acceptance criteria, independent review and quality floors remain in
force; frozen plans still require separate execution authorization.

## Release 2.31: bounded quality checks

The repository secret guard checks UTF-8 (including BOM) and UTF-16LE/BE with BOM.
Supported text is limited to 2 MiB per file. Oversize or malformed supported text
is refused without printing credential values. Binary files and BOM-less UTF-16
remain outside its decoded-text claim. Exact harmless path/key/value exceptions
are checked separately; the guard supplies repository evidence only.

The Python quality policy keeps the 76% statement and combined floors, adds a
71% global branch floor, and sets separate line/branch floors for four critical
files. Branch-enabled reports must use the pinned format and tool version, contain
all required files, and have consistent counters. Legacy policy receipts retain
their original interpretation. These floors provide regression checks.

Legacy adoption preparation validates state structure before reading mandatory
identity fields. Malformed v4/v5 input receives a bounded lifecycle error.
Preparation remains a read-only data candidate; history, expenses, original clocks
and expired authorization remain intact. Install the Python package for this fix.


## Workflow history and authorization renewal in 2.30

Install Python package 2.30 to use these commands. The portable plugin contains
skills and static documents; it uses the separately installed CLI.

`workflow init` creates v4 state. Use `workflow state-migrate` with
`--target-schema agent-workflow-state.v5` for an explicit v4-to-v5 conversion.
Supply the current `--expected-revision`, `--source-revision` and a unique
`--operation-id`. Conversion keeps an exact backup of the original state and
moves complete history into bounded immutable objects. Original costs, unknown
usage, budgets, clocks and authorization remain part of the run.

`workflow authorization-renew` consumes a distinct, fresh user receipt through
`--receipt`. It supports a consumed grant when a committed task is `VERIFYING`,
or the run is in `FINAL_AUDIT` with all required tasks accepted. The receipt
binds the current run, plan, source, state revision, previous grant, budgets,
clocks and task subjects. Renewal keeps the existing attempt and prior grant
history. Migration alone does not renew an expired grant. A blocked run needs
its existing blocker recovery route.

```bash
agent-lifecycle workflow state-migrate --help
agent-lifecycle workflow authorization-renew --help
```

See the [2.30 storage and recovery guide](https://github.com/avksp/agent-lifecycle-kit/blob/v2.30.0/docs/reference/workflow-state-storage.md)
for limits, backups, Git exclusions and the separate renewal contract.

## Migrating authority artifacts to 2.15

Version 2.15 tightens validation before artifacts can grant authority. Existing
valid distinct-key JSON retains the 2.14 canonical bytes, digests and trailing
newline convention. Do not rewrite historical manifests, locks or receipts;
correct invalid input in a new plan revision and repeat independent review and
freeze when authority-bearing inputs change.

- JSON object keys must be unique at every depth, including escaped spellings
  of the same key. Ambiguous input fails with `invalid-json` and
  `JSON input is invalid`; diagnostics do not echo keys, values, paths or payloads.
- Authority reads and writes use a root-bound guarded I/O boundary. Traversal,
  symlink escapes, Windows/UNC aliases and ancestor-swap races fail closed.
  A missing platform primitive does not turn a structural check into permission.
- Declare authority paths in NFC. An unambiguous observed filesystem spelling
  compares in NFC while retaining its original I/O and evidence bytes. Verified
  case-sensitive roots preserve distinct names such as `Foo.py` and `foo.py`;
  case-insensitive roots block ambiguous or protected aliases using NFC and
  casefold. Unknown filesystem semantics and ambiguous normalization fail closed.
  The same policy applies to `readOnly`, `forbiddenWrites`, `leadOwned[].path`
  and `workstreams[].writes`; normalization cannot broaden a write grant.
- Authority token/path fields reject control and display-spoofing characters.
  Decision-bearing prose uses the same protection while retaining TAB/LF/CR and
  language joiners U+200C/U+200D. Ordinary multilingual text, including English
  and Russian multiline prose, remains valid. A rejected field reports
  `authority-text-control` without echoing unsafe text; it is not silently repaired.
- Changeset ownership includes both the removed and added sides of a rename.
  A copy includes the changed destination, without assigning its unchanged
  source to the task.
- The compiler validates every packet and index destination before creating
  output directories or files. Declared/default outputs and explicit `--out-dir`
  cannot overlap protected plan inventory or escape the repository. Safe sibling
  layouts, disjoint shared-parent layouts and contained absolute exports remain
  supported. An explicit export does not override later adoption bindings.
  Guarded writes retain containment after preflight; this is not a general
  rollback guarantee for unrelated I/O failures.
- External-job cancellation `PASS` acknowledges publication of the cancellation
  request. It does not prove process termination; terminal evidence and cleanup
  remain separate. Initial terminal no-ops, idempotency and lineage are preserved.

See [Authority and artifact boundaries](authority-artifact-boundaries.md) for
`operation_root`, task-start and package-audit semantics. Rootless completeness
PASS proves offline structure only. Validator evidence remains bound to the
checked source and actual guarded-I/O consumers. These changes do not establish
host `ENFORCED` qualification or release readiness. Full regression, security,
architecture, neutrality, quality, documentation and publication gates remain
required with their existing thresholds.

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

Python 3.11-3.15 is supported. Install the exact release from the official
[PyPI project](https://pypi.org/project/agent-lifecycle-kit/):

```bash
python -m pip install agent-lifecycle-kit==2.35.0
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

## Release 2.18 security and compatibility

Process diagnostics redact complete bounded captures before choosing a tail. Stdin, stdout/stderr and Git protocols share deadlines and byte limits. Git identity disables external diff/textconv; historical receipts are not rewritten to a new digest. [OpenCode 1.x/2.x](../adapters/opencode.md) uses separate command grammar and effective installed-version qualification while preserving historical maturity. Plugin `exact` and inclusive same-major `range` policies (`2.0.30..2.0.32`) are enforced separately from full-host live qualification. Public trust roots may be readable; signing seeds require POSIX mode 0600/0400. RFC signature bytes are preserved; pure Python is not claimed constant-time.

## Release 2.17 workflow validation

See [workflow completeness and recovery](workflow-completeness.md) for the full contract. Unsupported CLI arguments fail before mutation; `workflow init --dry-run` is not supported. Technical review interruption uses `workflow block --review-task <task-id>` with `review-response-missing` or `review-response-truncated`, then authorized `workflow resolve` for the unchanged subject. This does not issue provider retries, reset usage or extend deadlines. Same-user OS locks serialize cooperating writers; unavailable host usage remains unavailable.

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
  Add `--strategy <receipt>` with the exact `--strategy-risk`, policy,
  descriptor, capability-manifest and project-profile inputs to adopt a fully
  bound execution strategy. The transition recomputes every digest and blocks
  stale or incomplete inputs before mutation.
- `agent-lifecycle workflow task-snapshot`: compute the current task-scoped
  Git file set and content digests without changing workflow state. Put the
  returned `claim` object in the task result before `task-result`. Add the
  all-or-none `--manifest`, `--lock`, `--phase-packet-purpose` and
  `--phase-packet-out` options to emit a separate bounded
  `agent-phase-packet.v1` for implementation, task audit or remediation.
- `agent-lifecycle workflow validation-select --state ... --task ...
  --manifest ... --lock ... --snapshot ... [--out ...]`: select frozen check
  IDs without executing commands or mutating state. Legacy and protected-path
  cases conservatively select `RELEASE_FULL`.
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
  opted-in plan requires final-audit quorum. An opted-in validation-ladder plan
  also requires `--release-full-receipt <release-full.json>` with exact current
  plan, lock, source, tree and catalog lineage.
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
- `agent-lifecycle start ... --strategy-out <path>` and
  `agent-lifecycle adapter task start ... --strategy-out <path>`: derive a
  create-only strategy for the exact next attempt on the managed path. A true
  `automaticAdoptionEligible` value is routing eligibility only; the receipt
  has `modelCallsStarted: false` and no implementation, acceptance or
  finalization authority.
- `agent-lifecycle workflow continue ... --strategy <path>
  --strategy-descriptor <path> --strategy-capability-manifest <path>
  --strategy-project-profile <path>`: project or apply task start through the
  same receipt. Continue still requires the normal projection guard and cannot
  lower validation or replace final `RELEASE_FULL`.
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
- `agent-lifecycle audit delta`: build read-only, command-free
  `agent-rework-delta-audit-receipt.v1` evidence across adjacent rework
  attempts. Uncertain or stale impact selects `FULL_AUDIT_REQUIRED`; this
  receipt never accepts a task.
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
- `agent-lifecycle metrics workflow-compare --before <path> --after <path>
  --out <path>`: compare immutable workflow-economics fixtures only when their
  stable workload and implementation identities match. Use
  `--comparison-pair` only for an exact canonical pair declared before both
  measurements; missing telemetry and weaker gates never become improvement.
- `agent-lifecycle metrics workflow-recommend --comparison <path>
  --current-mode <mode> --required-mode <mode> --out <path>`: create an
  advisory-only recommendation with no policy, workflow, acceptance or gate
  mutation authority. Add `--protected-work` for security, architecture,
  quality or release work.
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
The complete identity, pair and safety contract is documented in
[workflow economics](workflow-economics.md).
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

## Release 2.16 accounting and retention

ALK records cumulative task/run expenses and conservative holds for unavailable
usage. Admission, settlement and recovery are distinct; retries keep prior costs.
A budget or time overrun does not erase a valid result or authorize a fresh
attempt. Required evidence and independent acceptance still apply.

Host capabilities set the guarantee. The selected Codex CLI 0.162.1 route proves
only ALK-controlled input fit with private `features.apps=false`; full-host
usage stays `UNAVAILABLE`, and unsupported strong A5/protected closing refuses.
Other adapter source profiles are capability descriptions, not native proof.

Raw details become eligible 30 days after full financial closure. Configure an
hourly same-user maintenance command with pinned authority and a fresh finite
deadline, then verify the actual target. See the
[retention operations guide](../operations/retention-maintenance.md).


## Safe artifact and review helpers (2.19)

| Command or option | Effect |
| --- | --- |
| `task artifact-create --kind json --input <json> --out <new-file>` | Create-only canonical serialization; no acceptance authority. |
| `task artifact-create --kind task-result --state <state> --task <id> --input <json> --out <new-file>` | Existing typed result validator and current lineage; commit/review stay separate. |
| `task artifact-create --kind evidence --input <json> --out <new-file>` | Existing closed receipt and digest checks; no attestation by shape. |
| `task artifact-inspect --input <json> --max-display-bytes 8192` | Read-only redacted display with original path/digest and truncation metadata. |
| `plan freeze-prepare --manifest <draft> --out <new-directory> --repository-root .` | New bounded candidate, no accepting review/lock/authorization. |
| `plan verify --manifest <manifest> --out <receipt> --compact` | Compact summary with retained full typed receipt; default output unchanged. |
| `schema list --scope core` | Small view naming actual contextual validators; full registry remains default. |
| `review-mesh prepare ... --review-input <inventory> --repository-root . --out-dir <new-directory>` | Validate local inventory and generate reading index/response contract; no model launch or delivery proof. |

See [safe artifact authoring](safe-artifact-authoring.md) for limits, refusal
conditions and the review/freeze boundary, and [Review Mesh](review-mesh.md#bounded-review-handoff)
for inventory and raw/normalized response contracts. New authoring commands emit
compact non-authoritative summaries; existing commands keep their default output.


## Release 2.20: composed initialization and digest display

`workflow init --manifest` projects the actual local destinations without
writing. Run it from the selected repository root. The manifest selects the
packet directory; a different `--packet-output-dir` is refused before writes.
For nested state files the package root is derived unless supplied explicitly.

```bash
agent-lifecycle workflow init --manifest tasks/example/plan.manifest.json \
  --state work/example/run.state.json --run-id example-run --package-id example
```

Apply requires the full `bindingDigest` from a current projection and a unique
adoption operation ID:

```bash
agent-lifecycle workflow init --manifest tasks/example/plan.manifest.json \
  --state work/example/run.state.json --run-id example-run --package-id example \
  --apply --projected-target-digest <full-binding-digest> --operation-id initial-adoption
```

Apply requires an actually reviewed frozen v2 plan. It compiles the packet set,
creates state and adopts the plan in `AWAITING_AUTHORIZATION`. Execution still
requires the separate existing authorization command. Draft projection grants
no execution authority. Existing state, journals, incompatible ignored packets,
source drift and unsafe output aliases are refused. Complete exact packet sets
can be reused; an old run cannot be reused as a new run. Failure removes only
this invocation's unfinished outputs and retains competing writer data. A
completed packet set can remain after a later initialization failure. These
are local cooperating-writer guarantees, not continuous host attestation.

Enabled `contextCheckpointPolicy` is unsupported by the composed route and
refused before writes; use the existing explicit compile/init/adopt commands.
Without `--manifest`, `workflow init` retains its existing unbound-state behavior.

`workflow status --state <state> --full --digest-prefix-length 12` returns a
separate display view: `data` contains the complete original status, while
`displayIdentities` pairs each full SHA-256 with its display prefix. Collisions
expand within the rendered set. Prefix lengths range from 4 to 64. Prefixes
never replace persisted identities or become accepted authority inputs.

For deterministic local continuation, add `--local-only` to the existing
`workflow continue --until-blocked --apply` command, preserving all required
bundle, byte, transition and output limits. See [workflow continuation](workflow-continuation.md).
Public commands and live aliases remain supported; only unused private parser
builders were removed.

## Release 2.21: command accounting and recovery

The detailed [source-native accounting reference](source-native-workflow-accounting.md) explains supported quantities, provenance, qualified route limits and migration. Existing 2.14–2.20 accounting remains readable; missing measurements stay UNAVAILABLE.

```bash
agent-lifecycle --measure-request command-request.json --measure-out command-receipt.json version
agent-lifecycle adapter provider-preflight --profile .alk/host-launch/reviewer.json
agent-lifecycle adapter external-job recover --request request.json --job-root .alk/external-jobs
agent-lifecycle metrics goal-progress --input progress-input.json --now <unix-seconds> --out progress.json
```

Measurement options precede the ordinary command and require bounded source-bound request input. The progress input contains context, observations and qualified receipt bindings. The host-local response reader is an API, not a raw-output CLI. Provider inspection starts no model and does not infer auth/config/model readiness. Recovery starts no new generation and grants no acceptance. Missing trusted restrictions, chain/history or actual-target readiness refuses selected effects; unrelated direct host calls are outside this guarantee.

## Release 2.22: conservative plan review

The [plan-review reference](conservative-delta-review.md) explains FULL, DELTA_ELIGIBLE and FULL_REQUIRED, complete independent baselines, current per-seat applicability, composite coverage and agent-plan-lock.v3. Selection is advisory, starts no model and never authorizes execution. Missing evidence can be restored without repeating valid reviews. The ordinary full-review route remains supported; measured candidate model savings stay UNAVAILABLE.

```bash
agent-lifecycle plan review-packet --repository-root . --manifest tasks/my-plan-r2/plan.manifest.json --baseline tasks/my-plan-r1/review.json
```

## Compact S0/S1 packages in 2.23

[Compact DRAFT authoring](tier-proportional-plan-packages.md) preserves checks, independent review and separate authorization. Explicit acceptance-criteria.md and planFiles completion are required before freeze; UNKNOWN metrics are never zero.

## Release 2.26: bounded discovery and precise quality gates

Markdown imports bound examined entries, directories, depth and cooperative
elapsed time; see the [security control map](../security/release-security.md). Tracked-source checks
reuse the existing bare-token families. [Quality controls](../architecture/system-architecture.md)
require both combined and statement coverage of 76 percent and retain legacy
policy interpretation. The existing [reading pilot](../guides/controlled-technical-english.md) and host limits
remain; measurements do not establish token savings or host enforcement.


## Release 2.28 performance measurements

Release 2.28 adds [bounded lifecycle and accounting baselines](performance-and-resource-budgets.md#release-228-lifecycle-and-accounting-baselines). Repository tools measure real read-only operations and separate fixture preparation from operation and subprocess time. The Windows fixture comparison observed a 13.08% median reduction in one six-sample experiment; it is not a universal speed promise. All security and platform checks remain required.
