# Model routing

Model routing selects a provider-neutral model class for lifecycle phases and
task attempts. It does not call provider APIs and does not store concrete model
names in portable plans, task packets, locks, or workflow state.

When a task attempt is started, the selected route is copied into
`attemptModelRoute`. For model-backed routes, `workflow task-result` requires a
host-attested `agent-lifecycle-model-usage-receipt.v1` bound to the same run,
task, attempt, plan digest, source revision and route decision digest.

## Core commands

```bash
agent-lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
agent-lifecycle model profile-check --type host --profile <host-model-profile.json>
agent-lifecycle model route --profile profiles/model-routing-profile.v1.json --host-profile <host-model-profile.json> --request <model-route-request.json>
agent-lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
```

`model route` is deterministic. The same request, routing profile, and optional
host profile produce the same decision digest.

Route requests may include optional `lifecycleMode` and `qualityFloor` values
from an adaptive lifecycle decision. The resolver rejects requests where the
mode is below the floor. Low-risk S0/S1 `light` work can route to the `budget`
class, but critical review, local-only policy, context and capability gates
remain authoritative.

Small-model packets are compatible with budget or local compact implementation
routes only when the adaptive quality floor permits them. They do not make a
small/local route valid for critical review; final audit and security-sensitive
review still require calibrated review-capable classes.

## Failure-aware escalation

Route requests may include optional `failureSignals` from classification,
validation, retry, remediation or flake receipts. These signals are neutral:
they use failure classes, retry counts, flake status, validation status and
receipt digests, not provider or model names.

The resolver starts with the normal lightest safe class, then applies a bounded
progressive ladder:

```text
no-model -> local-small-packet -> standard-implementation -> stronger-review -> optional-cross-check
```

Validation failures, API-contract, serialization, permission, migration or
performance classes can escalate low-risk work to standard implementation.
Security bugs, race conditions, flaky tests, repeated retries or repeated
remediation loops escalate to stronger review. A repeated failure never
downgrades below the previous provider-neutral model class.

The route decision records an `escalation` summary with reason codes,
`failureClass`, retry/remediation counts, `optionalCrossCheckRecommended`,
`downgradeBlocked`, `qualityFloorPreserved: true` and
`providerModelNamesInCore: false`.

## Model classes

| Class | Purpose |
| --- | --- |
| `no-model` | Deterministic validation, schema checks, context checks and pure file checks. |
| `budget` | Low-risk S0/S1 triage and bounded mechanical work. |
| `local-compact` | Explicit local 4k/8k bounded work only. |
| `standard-code` | Standard S1 implementation and implementation review. |
| `local-standard-code` | Local S0/S1 code work with calibrated JSON, tool-use and context support. |
| `strong-reasoning` | S2 specification, independent review, security/performance/final audit and release gates. |
| `local-strong-review` | Local critical review only after explicit capability, context, usage and calibration gates pass. |
| `specialist-review` | Host-specific specialist reviewer when explicitly configured. |

## Host model profiles

Concrete model names belong in host-local profiles:

```json
{
  "schemaVersion": "agent-host-model-selection-profile.v1",
  "host": "local-host",
  "profileId": "local-host-profile",
  "budgetModeDefault": "subscription",
  "bindings": {
    "local-strong-review": {
      "providerModel": "<host-specific-local-review-model>",
      "contextWindow": "32k",
      "capabilities": ["text", "json", "tool-use", "deep-review"],
      "jsonReliability": "strict",
      "toolUse": "supported",
      "allowedForTiers": ["S1", "S2"],
      "allowedForPhases": ["independent-review", "security-review", "performance-review", "final-audit"],
      "usageAccounting": "host-attested",
      "dataPolicy": "local-only",
      "calibrationStatus": "PASSED",
      "reviewStrategy": "large-context-or-sliced-review"
    }
  },
  "fallbackPolicies": {
    "standard-code": ["strong-reasoning"],
    "strong-reasoning": ["specialist-review"]
  },
  "redactionPolicy": {
    "providerModel": "hash",
    "provider": "omit",
    "variant": "omit"
  }
}
```

Profile validation redacts provider model names from validation output. The
profile can be untracked or stored in host-specific local configuration.
The validator also accepts the earlier `agent-lifecycle-host-model-profile.v1`
shape for compatibility, but host-local profiles should use
`agent-host-model-selection-profile.v1` so the budget mode, fallback policy and
redaction policy are explicit.

Bundled examples live under `profiles/hosts/` and use placeholders such as
`<codex-host-local-strong-reasoning-model>`. Replace those placeholders only in
host-local configuration or live evidence. Do not commit personal subscription,
provider, or local model settings.

## Local-only critical review

Local execution is not automatically weak, but small local models are not
automatically review-capable. `local-compact` cannot satisfy final audit,
security review, performance review, production promotion, or S2 independent
review.

If policy is `local-only` and no local binding satisfies the critical review
gates, the lifecycle must block, return `CONDITIONAL`, request human review,
split/refreeze the review scope, or ask for explicit approval to use a stronger
non-local class.

## Policy presets

Use a policy preset instead of asking for a model on every task:

- `cost-optimized`
- `balanced`
- `quality-first`
- `local-only`
- `manual`

Interactive questions are reserved for missing budget limits, data policy,
cloud/local restrictions, or unavailable critical-review capability.

## Usage receipts

Model-backed operations must produce
`agent-lifecycle-model-usage-receipt.v1` with normalized metrics:

- `inputTokens`
- `outputTokens`
- `billableTokens`
- `cumulativeContextBytes`
- `toolCalls`
- `wallSeconds`

`model usage-check` validates host attestation, route binding and budget
ceilings. In workflow execution, missing, unattested or lineage-drifted usage
blocks `workflow task-result` before a task can enter review.

Host-local parsers may emit the same receipt as a bound sidecar without
changing the host-operation schema. Core aggregation treats it as attested only
when both `source: host` and `status: ATTESTED` are present and the declared
normalizer is qualified. See
[Host-local token accounting](host-local-token-accounting.md).

Risk-aware attempts add `usage.invocations` to the same host-attested receipt.
The bound risk profile checks `billableTokens`, `invocations`, and
`wallSeconds`; exceeding any cap rejects `workflow task-result`. This additive
field is required only when `workflow task-start --risk-profile <path>` has
authorized the attempt. See [Risk-aware execution](risk-aware-execution.md).

## Scope boundaries

The v1 implementation enforces route receipts without becoming a provider
broker:

- no provider API clients in core;
- no live price lookup;
- no cross-provider broker;
- no automatic marketplace/model shopping;
- no mandatory per-task questionnaire;
- no prompt-only heuristics without route reason codes.

Adapters remain responsible for mapping `attemptModelRoute.modelClass` to a
host-local concrete model and for returning the usage receipt. If a host cannot
execute or attest the selected route, it must fail closed instead of silently
downgrading.

## Stage execution bindings

An optional local binding connects a stage's neutral model class to an exact
adapter, host model profile, launch profile and reasoning effort. The existing
resolver still checks risk, context, data policy, capabilities and independence.
Each stage can list up to three approved bindings, including its primary route.
Different stages can use different entries from a registry of up to 32 bindings.

Start with discovery or provide a manual draft:

```sh
agent-lifecycle model setup --discover --scope project
agent-lifecycle model setup --manual --input local-bindings.json --scope project
```

The manual input is a closed object with `projectProfile` and `registry` members.
`projectProfile` is an ordinary project workflow profile. `registry` uses
`agent-local-stage-bindings.v1` with a `bindings` object keyed by local IDs.
Each entry contains:

| Member | Content |
| --- | --- |
| `adapterId` | The existing adapter ID. |
| `hostModelProfile` | Contained `path`, raw `sha256` and neutral `modelClass`. |
| `launchProfile` | Contained `path` and raw `sha256` of the existing local launch profile. |
| `hostParameters` | The exact `reasoningEffort`; no silent conversion. |
| `parameterSupport` | `allowedEfforts` and an `evidence` path/hash for declared documented support. |
| `qualificationEvidence` | The path/hash of the existing exact-version launch qualification receipt. |

Linked files belong under `.alk/host-launch`. Model names stay in the existing
host model profile. Parameter support is a declared local input, not proof that
a model is available or suitable. Missing configuration returns `MISSING_INPUT`.
Discovery checks known CLI identities with finite process/time/output limits.
It does not install software, read credentials, log in or call models. When a
host has no supported model listing, use manual input and retain the unverified
status. A discovered CLI is not an available model.

Both setup forms are read-only until explicit apply:

```sh
agent-lifecycle model setup --manual --input local-bindings.json --scope project --apply --expected-profile-digest CURRENT_RAW_SHA256
```

For first creation use `ABSENT` instead of the current raw file SHA256. Apply
creates an immutable registry and commits the project profile pointer last;
it refuses a changed profile, unsafe path or conflicting output. Use project
scope; this setup does not write user-wide defaults.

Inspect the selected stage and check a configured binding without a model call:

```sh
agent-lifecycle model explain --stage implementation --project-profile .alk/project-profile.json --request route-request.json
agent-lifecycle model availability --binding primary --project-profile .alk/project-profile.json
```

Local views show model/effort and the reason for each accepted or rejected
candidate. Use `--portable` to emit neutral classes, digests and reason codes
without local names or argv. Preserve separate executable, configuration,
authentication, probe and task-quality states. An unavailable value is not zero.
The priority order is yours; ALK does not claim the cheapest or best model.

### First probe and native execution

Prepare a fresh ordinary local profile for the actual CLI, then run
`agent-lifecycle host-launch preflight --profile LOCAL_PROFILE` once. Its
canonical receipt binds that profile, executable and version. Reference that
exact policy receipt in `qualificationEvidence`. It proves no model call,
model availability or task quality.

An explicit bounded probe can establish the first availability observation:

```sh
agent-lifecycle model availability --binding primary   --project-profile .alk/project-profile.json --probe   --authorization-receipt work/execution-authorization.json   --state work/run.state.json --manifest plans/feature/plan.manifest.json   --lock plans/feature/plan.lock.json --task WS-01   --operation-id PROBE_OPERATION --expected-revision REV --source-revision SOURCE_SHA   --max-invocations 1 --max-wall-seconds 60 --max-output-bytes 65536
```

Use actual current lineage and permission for the diagnostic. The first probe
may lack a previous positive availability observation; all native authorization,
profile, risk, source and original-deadline checks still apply. It cannot accept
a task or replace the active implementation binding. Ordinary automatic selection
needs its required fresh evidence. A separate managed task and independent
acceptance establish the supported task scenario.

Fallback occurs only before attempt adoption, for proved pre-dispatch
unavailability and an already approved eligible reserve. Active attempts keep
their binding. An unknown spawn, timeout or lost response requires reconciliation
or a block, with no blind second dispatch. Code and test failures use remediation.
Keep all attempts, original deadlines and expenses. One CLI invocation can contain
several provider requests; missing token, request or invoice data stays unavailable.

Native support follows exact local qualification. The initial binding consumer
uses the ordinary Codex route. Other hosts remain unqualified until their own
proof; the separate `codex-exact-prompt-v1` route refuses this opt-in. The running
coordinator does not change model. See [project workflow profiles](project-workflow-profile.md)
and [the SDLC boundary](../architecture/sdlc-boundary.md).

### Adopt before launch

Binding selection and attempt adoption are separate operations. For a frozen
implementation task, use `start --strategy-out PATH` with the current stage,
project profile and full workflow bindings to prepare the selected strategy.
Preparation creates its artifact, with no host call or execution permission.
Then use the existing `workflow task-start --strategy PATH` and its required
trusted policy/profile inputs. The native transition recomputes and stores only
the neutral binding/configuration identity. After adoption, `start --launch`
can use that same stored identity. It refuses an unbound or different active
attempt; changing local configuration does not silently change the attempt.
Use the returned exact preparation command when adoption is missing. The
read-only managed workflow projection does not start an attempt.

Unknown, expired or changed primary observations block selection and request an explicit bounded probe; they do not prove unavailability for fallback. A positive probe requires a complete successful Codex JSONL model response, including an agent message and terminal completion. Exit 0, help or version output is insufficient. Backend identity and effort remain unattested.

## Declared source completion when complete host usage is unavailable

A model-backed attempt needs a usage receipt before `workflow task-result`.
A successful model response or availability probe does not replace that receipt.
The default usage contract still requires the host evidence selected by the plan.

A reviewed frozen plan can explicitly select `SOURCE_AUTHORING_LIMITED` with
`alk-source-usage-completion-policy.v2` and `PROJECT_DECLARED_SOURCE`. This optional
route uses an original declared carry, a frozen source prefix, and a separate
admission for each task attempt. The source must preserve prior declared units,
known partials, unknown intervals and original timestamps. A service booking is
not a measured token count or an invoice amount. An incomplete financial Journal
still refuses financial reservations; this route does not change that rule.

The existing v2 usage receipt reports all seven whole-host metrics as `null` with
`UNAVAILABLE` states. Its attestation is `alk-declared` / `UNAVAILABLE`. Actual cap
conformance stays `UNAVAILABLE`; financial closure stays `OPEN_UNAVAILABLE`.
Independent review, typed audit, task acceptance and finalization remain required.
Native task completion under this limited contract does not settle financial costs.
A requested hard cap that cannot be observed still blocks.

Use `workflow source-usage-prepare` to prepare the declared source data. Opening
requires carry and explicit actor/task/role bindings; admission and receipt phases
check the current frozen plan, authorization, source, attempt and financial frontier.
The current financial head is selected by the frozen policy, never by a receipt.
Keep source snapshots private and preserve their exact bytes as opaque `.raw` files.
The producer writes new structured artifacts as canonical JSON. Changes to the
source, prefix, actor, binding or frontier require a refusal or explicit recovery.
This mode is never enabled automatically after a missing or failed v1 receipt.


## Opt-in qualified evidence ranking

`benchmark rank-qualified` offers an advisory ranking within an explicit local
candidate allowlist. Manual selection remains the default:

```json
{"schemaVersion":"agent-qualified-route-ranking-request.v1","enabled":false}
```

```bash
agent-lifecycle benchmark rank-qualified --request local-ranking.json --out new-report.json
```

The request and optional new output must be regular files within the caller's
repository directory; links and traversal are refused. The command never calls a
model, starts a host, modifies a profile or adopts a route. Omit `--out` to print
the report without a file write. Disabling ranking changes no selection state.

Enabled requests run the existing model resolver before considering economics.
Deterministic work returns `NO_MODEL_REQUIRED`; tier, risk, data, context,
capability, lifecycle quality and failure-escalation floors remain authoritative.
Local-only requests are evaluated against each supplied host profile. Every
selected binding requires `calibrationStatus=PASSED`. Availability, manual
selection, onboarding, launch authority and the existing bounded failure/fallback
mechanisms still apply separately. A recommendation is no permission to launch.

See [the benchmark evidence contract](benchmark-qualification.md#qualified-evidence-ranking)
for enabled input and complete accepted-task resource requirements. Incomplete,
stale, untrusted or incomparable evidence anywhere in the allowlist refuses the
whole request with `NO_RECOMMENDATION`; the command does not drop a candidate to
manufacture a winner. Input errors return a bounded error and nonzero exit.

Reports contain candidate IDs, binding digests, classes and integer metric totals,
never private provider/model names. `advisoryOnly=true`,
`automaticRouteAdoptionEligible=false`, `liveEconomicQualification=UNQUALIFIED`
and `savingsClaimed=false` always apply. Positive synthetic tests are `UNIT_ONLY`;
live economic qualification and production promotion remain deferred. Digest
membership does not attest a producer's identity or complete collection of calls.
