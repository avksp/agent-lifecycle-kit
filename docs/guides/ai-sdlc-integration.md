# Integrate an external AI SDLC client

An external client can invoke the installed `agent-lifecycle` CLI as a bounded
subprocess and display its receipts. A task tracker, IDE, script or other client
uses the same contract; no task-tracker service or private Python import is
required. ALK owns workflow authority. The client owns process execution,
presentation and reconciliation. The host owns model execution and genuine usage
attestation; an independent reviewer owns review conclusions.

This guide defines a provider-neutral CLI consumer contract.
It adds no server, daemon, provider broker, runtime API or second state machine.
The supported surface below is deliberately bounded. Other operations retain
their [CLI contracts](../reference/cli.md).

## Negotiate before mutation

The client MUST run `agent-lifecycle version` and require
`agent-lifecycle-version.v1`. It MUST compare `version` with its explicitly tested
version mapping. A tested contract does not qualify another release
merely because its version looks similar. The client MUST refuse mutations for
an unknown version, unknown `schemaVersion`, unsupported action or incompatible
required field. Read-only diagnostics can remain available, clearly labelled as
unqualified. Do not guess flags, silently drop guards or downgrade a schema.

Use `agent-lifecycle schema list --scope core` and
`agent-lifecycle schema show <schema-id>` for the available descriptive contracts;
use the installed command's `--help` for its arguments. The registry is not a
universal wire protocol or authorization service. Runtime validators also check
cross-file bindings. Keep a client-owned mapping of tested versions, operations,
receipt/action schemas, required fields and refusal outcomes.

Invoke an argument array with shell evaluation disabled. Use an explicit
repository working directory, bounded input/output and timeout, and preserve
stdout, stderr, exit code, timestamps and exact executable identity. On timeout,
process failure, malformed/truncated output or an unknown receipt, record an
unknown result and reconcile before another mutation. CLI argument errors can
write parser diagnostics to stderr instead of JSON. A handled lifecycle error
uses `agent-lifecycle-error.v1` and exit 2. Exit 0 alone does not prove success:
`workflow continue` can return `INPUT_REQUIRED`, `WAITING` or `BLOCKED` with exit 0.

## Bind one request to native authority

The client MUST retain the repository, package ID, plan revision and full plan
digest, reviewed manifest and lock identities, run ID/state path, current state
revision, source revision, task ID and attempt when applicable. Bind all supplied
result, review, audit, usage and proof artifacts to that same lineage. Paths for
continuation inputs are repository-relative. Full digests are identities; a
shortened display value is not an input substitute.

The frozen manifest and `agent-plan-lock.v2` bind the reviewed plan. Freeze does
not authorize execution. Native state and transitions govern authorization,
dependency readiness, ownership, attempts, independent acceptance and completion.
Current native state formats include `agent-workflow-state.v4` and
`agent-workflow-state.v5`; support is an explicit client mapping, never permission
to rewrite or migrate state automatically. Legacy migration uses its separate
guarded command. A UI status is a projection of these facts, not authority.

## Bounded operation map

Each row names an existing command, its relevant schema/guard and its boundary.
Optional receipt output files are evidence writes, not workflow authority writes.

| Actor and operation | Existing command and schema/guard | Refusal and boundary |
| --- | --- | --- |
| Client: identify installation | `agent-lifecycle version`; `agent-lifecycle-version.v1`, `version` | Unknown version/schema refuses client mutation; no state transition. |
| Client: verify plan inputs | `agent-lifecycle plan verify --manifest <manifest> --package-root <plan-root> --acceptance <checklist> --repository-root . --out <receipt>`; `agent-plan-verification-receipt.v1` | Inspect `status`, named checks and blockers. Missing/drifted lock, invalid traceability or ownership refuses readiness. Structural verification is not semantic review, authorization or acceptance. |
| Client: project next action | `agent-lifecycle workflow continue` with the bindings below; `agent-workflow-continuation-receipt.v1`, nested `agent-workflow-continuation-action.v1` | Without `--apply`, no authority mutation. `requiredInputs`, blockers and route eligibility remain authoritative; projection launches no host or model. |
| Authorized controller: apply one supported action | Same `workflow continue` request plus `--apply --projected-state-revision <n> --projected-action-digest <full-digest>`; same receipt/action schemas, existing transition validators | Requires current revision, exact action digest, source/plan/lock lineage and authentic route-specific inputs. Missing inputs, stale lineage, missing authorization, invalid ownership or independent review refuse the transition. Only `APPLIED` with matching committed state/event establishes application. |
| Controller/host: select model class | `agent-lifecycle model route --profile <routing-profile> --host-profile <host-profile> --request <request>`; input `agent-lifecycle-model-route-request.v1`, output `agent-lifecycle-model-route-decision.v1` | Deterministic policy/capability/context/critical-review checks; unsuitable critical routes refuse. A decision launches no model and grants no workflow transition. |
| Host/controller: validate usage | `agent-lifecycle model usage-check --receipt <usage> --route-decision <decision> --budget-targets <targets>`; input `agent-lifecycle-model-usage-receipt.v1` | Validates host attestation, route binding and budgets; invalid/unattested usage returns `model-usage-validation-failed`. Validation alone cannot accept a task. |

The model route and usage commands accept some optional flags; this consumer
contract supplies the explicit profiles, decision and budget targets so their
identities are reviewable. Use [Model routing](../reference/model-routing.md)
for existing role classes, quality floors, critical-review rules and host-local
model mapping. Portable plans do not select concrete provider models. This guide
does not replace that routing policy or qualify a new host.

## Project, supply inputs, then apply

This is a command template, not authorization to mutate a real run:

```bash
agent-lifecycle workflow continue \
  --state work/run.state.json \
  --manifest work/plans/release-x/plan.manifest.json \
  --lock work/plans/release-x/plan.lock.json \
  --operation-id client-start-WS-01-attempt-1 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --reason "project a bounded task start" \
  --task WS-01
```

For a qualified receipt, the client MUST check `mode: PROJECT`, `stateWritten:
false`, `modelCallsStarted: false` and `hostLaunchStarted: false`, then inspect
`status`, `plan`, `stateBefore`, `action`, `requiredInputs` and `blockers`.
`READY` means that this action can be submitted to its guards. It does not mean
the task has started or finished. When `nextAction.argv` is present, it contains
argument tokens with `shell: false`; verify the executable, bindings and allowed
route before invoking them. Never execute receipt content as a shell string.

Supply the inputs requested by the actual route, then project again if the
inputs changed. Preserve the operation identity. To apply, use the same request
and inputs with `--apply`, the returned `action.stateRevision` as
`--projected-state-revision`, and its full `action.actionDigest` as
`--projected-action-digest`. Keep `--expected-revision` current. ALK recomputes
the action and calls its existing transition; a cached projection cannot bypass
the guards. An applied one-step receipt uses `mode: APPLY`, `status: APPLIED`,
`stateWritten: true`, `stateAfter` and `appliedEvent` for the committed revision.

| Projected route | Inputs and native boundary |
| --- | --- |
| Authorization / run start | `--authorization-receipt` when required; reviewed plan, matching lock and separate execution authorization. A draft or `PLAN_ONLY` is insufficient. |
| Task start | Eligible `--task`; `--risk-profile` or strategy inputs when required by the selected route. Native dependency, ownership, attempt and budget guards still apply. Recording task start does not launch a host. |
| Task result | `--result`, plus `--model-usage-receipt` and `--budget-targets` where required. Current source/change-set claims and authentic bound usage are checked before review. |
| Task review outcome | `--review`, `--implementation-audit` where required, and `--finding-id` for applicable remediation. The independent reviewer supplies the conclusion; the controller applies it. |
| Final audit outcome / finalization | `--final-audit` and outcome-specific `--verdict`, `--task-id`, `--finding-id`; finalization additionally consumes the required proof, integrity and completion-gate inputs. Follow the projected `requiredInputs` and the existing finalization gates. |

See [Workflow continuation](../reference/workflow-continuation.md) for the full
existing flag map and bounded bundle mode. The client MUST stop at host, model,
reviewer, operator, plan-authority or resource boundaries. It MUST NOT create
synthetic review/usage attestations, edit state/lock by hand or turn a local
`done` boolean into native acceptance. Task acceptance, final independent audit,
native finalization and downstream publication remain separate gates.

## Reconcile an unknown result

Before dispatch, retain one operation ID with the exact request, projected state
revision/action digest and input identities. ALK's native operation ledger rejects
an already-used operation ID; it is not a cached-response service. A retry with
a new ID is not a safe way to discover whether the previous mutation happened.

After a lost response, the client MUST stop mutation and read the canonical state,
its declared event journal and any retained native receipt. Match run/package,
operation ID, committed revision, event type/task/attempt and artifact bindings.
Workflow events use `agent-workflow-event.v1`. If the matching event and state
establish the intended transition, record that observed fact and project the next
action without repeating it. Do not infer success from a later revision alone.

If the operation is provably uncommitted and the state/journal agree, obtain a
fresh projection and follow the existing unused-operation guards before retry.
If evidence is missing, contradictory or indicates partial persistence, retain
UNKNOWN and stop for the existing recovery/operator route. Do not repair history
by writing a success event or replaying a host command. Native operation guards
do not guarantee exactly-once execution of arbitrary host/model/external side
effects; those require their own host-owned reconciliation evidence.

## Reference caller resource boundaries

The stdlib-only reference in `tests/cli/test_external_consumer_contract.py`
drains two unbuffered pipes concurrently. Each stream reads at most 1 MiB plus
one overflow-detection byte; it creates no output capture files. The runtime
deadline is 20 seconds after process creation returns. A separate cleanup window
is at most two seconds, covering direct-child stop/reaping and reader joins.
OS process creation itself is not interruptible by this deadline.

Timeout, overflow, invalid UTF-8/JSON, unknown output or unconfirmed cleanup
records `UNKNOWN`, clears qualification and blocks all further calls. A unique
bounded state/event match can resolve effect uncertainty; renegotiation is still
required before mutation. It cannot clear unconfirmed resource cleanup: dispose
that caller. Never retry a mutation to discover whether it succeeded.

Executable hashing streams at most 32 MiB plus one detection byte before launch.
This is an observed file identity, not attestation of every loaded runtime file.
Reconciliation admits only regular non-symlink relative artifacts inside its
working directory: state at most 1 MiB, event log at most 4 MiB, at most 1024 lines,
and each line at most 65536 bytes including its newline. State is compared again
after reading events; missing, changed, ambiguous, oversized or malformed input
stays `UNKNOWN`. These checks are not an atomic filesystem snapshot or a sandbox
for arbitrary executables, descendants or hostile concurrent filesystem changes.

The eight disposable public cases also exercise a legacy v3 state fixture;
they do not migrate native authority. Source/editable checks are intermediate
proof. A final installed wheel needs its own exact-version qualification.

## Keep usage and evidence honest

Retain exact source, executable/configuration/input digests, command/exit/time,
receipt and changed-file identities. Record genuine model usage through the
existing host-attested receipt and qualified normalizer; a UI estimate, fixture
or serialization helper cannot attest usage. Model-backed task results refuse
missing, unattested or lineage-drifted usage. Unavailable tokens, provider cost
and full host input remain `UNKNOWN`/null, not measured zero. Keep shell/process,
validation, model invocation and physical CI counts separate, and retain prior
costs, failed attempts and original clocks across retries.

Disposable-fixture conformance is `UNIT_ONLY`. A deterministic consumer test can
observe zero model calls; it proves neither live review, host enforcement nor
production qualification. See [Host-local token accounting](../reference/host-local-token-accounting.md)
and [Safe artifact authoring](../reference/safe-artifact-authoring.md). A valid
JSON artifact does not make its claims true or complete a bound run.
