# Project workflow profile

A project workflow profile is a small, project-local defaults file for the
unified ALK start command. It helps a team use the same stage names, default
adapter, risk level, review mode and bounded resource limits without putting
project preferences into the ALK plan.

The profile belongs to the consuming project. The standard
`.alk/project-profile.json` path is ignored by Git and is intended for local
use. It may remain between runs, but it must not be committed or treated as
project source of truth. It is not a replacement for a specification, frozen
plan or plan lock.

## Create and check a profile

Create the minimal valid profile in the current project:

```bash
agent-lifecycle project profile init --adapter <adapter-id> --out .alk/project-profile.json
```

The optional `--adapter` value becomes the default for `start`. If it is
omitted, edit `defaultAdapter` in the local file or keep passing `--adapter`
for each run. Then resolve the profile before a run:

```bash
agent-lifecycle project profile check
agent-lifecycle project profile check --adapter <adapter-id> --risk S1
```

For a frozen implementation plan, bind both authority artifacts:

```bash
agent-lifecycle project profile check \
  --manifest path/to/plan.manifest.json \
  --lock path/to/plan.lock.json \
  --out .alk/effective-project-profile.json
```

The check emits `agent-effective-project-workflow-profile.v1`. It does not
start a model, launch an adapter, change the plan or write source files.

## Use a built-in workflow preset

For a common route, inspect and validate a built-in preset before creating the
local profile:

```bash
agent-lifecycle project preset list
agent-lifecycle project preset inspect --preset research-review
agent-lifecycle project preset validate --preset research-review
agent-lifecycle project preset render \
  --preset research-review \
  --adapter <adapter-id> \
  --out .alk/project-profile.json
```

The rendered file is an ordinary local project profile. For a one-off task,
skip rendering and pass `--preset <preset-id>` to `start`. Preset values are
the lowest-priority defaults: explicit command-line values override the local
profile, and a frozen plan can raise requirements. See [Workflow presets](workflow-presets.md)
for the complete matrix and stage limits.

## Use the profile with start

With `.alk/project-profile.json` in the current project, `start` discovers it
automatically. The profile can supply the default adapter, so the beginner
path is:

```bash
agent-lifecycle start --file task.md
agent-lifecycle start --text "Investigate the cache failure"
```

Select a profile explicitly when working from another contained path:

```bash
agent-lifecycle start \
  --project-profile .alk/project-profile.json \
  --file task.md
```

An explicit CLI adapter remains available for a one-off choice and takes
precedence over the profile default:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --project-profile .alk/project-profile.json \
  --mode research \
  --file research.md
```

Use `--no-project-profile` to make the advanced route reproducible without
local defaults:

```bash
agent-lifecycle start \
  --no-project-profile \
  --adapter <adapter-id> \
  --mode review \
  --file proposed-plan.md
```

## Profile fields

The portable fields are intentionally small:

| Field | Purpose |
| --- | --- |
| `defaultAdapter` | Adapter used when `start` has no `--adapter`. |
| `defaultMode` and `defaultRisk` | Default lifecycle preparation mode and risk tier. |
| `policies` | Relative references to existing ALK policy, routing, baseline, host model and review-mesh profiles. |
| `stages` | Defaults for `intake`, `research`, `planning`, `review`, `implementation`, `audit` and `finalization`. |
| `principles` | A contained project-principles path, digest and `sourceOfTruth: false`; it supplies context but no implementation authority. |
| `guidanceRef` | A bounded, relative reference to host-owned guidance metadata for one stage. |

Stage settings may select an existing ALK mode, a neutral model class, a review
mode and bounded `maxAttempts`, `maxInvocations` or `maxWallSeconds`. The
profile stores no provider, account, credential, secret or system-prompt
authority.

Example:

```json
{
  "schemaVersion": "agent-project-workflow-profile.v1",
  "profileId": "checkout-project",
  "defaultAdapter": "<adapter-id>",
  "defaultMode": "auto",
  "defaultRisk": "S1",
  "policies": {
    "routingProfile": "profiles/model-routing-profile.v1.json",
    "baselineProfile": "profiles/review-mesh-profile.v1.json"
  },
  "stages": {
    "research": {
      "modelClass": "standard-code",
      "reviewMesh": "parallel-research-synthesis",
      "maxAttempts": 2,
      "maxWallSeconds": 1800,
      "guidanceRef": "docs/agent-research-guidance.md"
    },
    "implementation": {
      "risk": "S1",
      "reviewMesh": "implementation-audit-panel",
      "maxAttempts": 3
    }
  },
  "productionPromotionClaimed": false
}
```

### Optional thread bridge

The optional `threadBridge` field enables bounded access to host-owned threads
for selected phases. It is `off` by default and supports `read`, `list`, `send`
and `create`. Read/list rules use no operator approval; send/create rules use
operator approval and an idempotency key.

```json
{
  "threadBridge": {
    "mode": "read-only",
    "operations": {
      "read": {"enabled": true, "scope": "explicit-target", "approval": "none", "blocking": "required"},
      "list": {"enabled": true, "scope": "project", "approval": "none", "blocking": "non-blocking"},
      "send": {"enabled": false, "scope": "explicit-target", "approval": "operator", "blocking": "required"},
      "create": {"enabled": false, "scope": "project", "approval": "operator", "blocking": "required"}
    },
    "phaseRules": {"research": {"read": {"enabled": true, "scope": "explicit-target"}}},
    "limits": {"maxImportedBytes": 32768, "maxImportedTokens": 2048}
  }
}
```

The bridge policy controls permission and resource bounds; the adapter owns the
native thread API. Imported thread content is additional context with no plan,
acceptance or proof authority. See [Optional thread bridge](optional-thread-bridge.md).

References stay inside the project root. The `.alk/` exception is reserved for
operator-local host model and launch profiles. The profile loader checks path
components and rejects traversal, absolute paths, URLs and symlink escapes.

## Authority and receipts

The effective order is:

1. mandatory ALK lifecycle rules;
2. the frozen plan and matching lock;
3. explicit command-line values;
4. the project profile;
5. preset defaults.

A lower layer can fill a default but cannot reduce the plan's risk tier,
quality floor, write scope, required gate or receipt requirement. The profile
digest is carried into the execution strategy and task packet projections.

For managed task start, this precedence is materialized in the
`agent-execution-strategy.v1` receipt. The receipt binds either the exact
effective profile digest and path or a canonical `ABSENT` identity. A changed
profile cannot affect an attempt already in progress and cannot be silently
reused for the next attempt: derive a fresh strategy with `--strategy-out`.
Capability evidence affects only whether the selected route can be enforced;
it never chooses a weaker value.

Without an active profile, `start` keeps the existing
`agent-lifecycle-start-receipt.v1` contract. With an active profile, the facade
returns `agent-guided-action-receipt.v1`, which contains the base start receipt,
the effective profile summary, its digest, the stable stage guidance projection
and the next action. The projection reports bounded guidance metadata for the
current stage; it does not copy or execute the referenced file. This makes the
guided path observable while preserving the atomic lifecycle receipts.

Project profiles guide a host; they do not execute guidance text or provide
prompts to a model. The host adapter remains responsible for loading its own
local instructions. For the full lifecycle and atomic commands, see [Workflow
customization and execution controls](workflow-customization.md) and [the CLI
reference](cli.md).

For durable project context and controlled changes between plan revisions, see
[Project principles and plan deltas](project-principles-and-plan-deltas.md).

## Bind a stage to local execution profiles

Set optional `policies.executionBindings` to the contained local registry and
give each opted-in stage an ordered `executionBindingRefs` list. For example,
the local settings can include:

```json
{
  "policies": {"executionBindings": ".alk/host-launch/stage-bindings-RAW_SHA256.json"},
  "stages": {"implementation": {"executionBindingRefs": ["primary", "reserve"]}}
}
```

This is a fragment, not a complete project profile. `model setup --manual --input`
validates the full project-profile/registry pair; explicit `--apply` saves it with
a checked current profile digest. See [model routing](model-routing.md#stage-execution-bindings)
for its input members, discovery, availability and first-probe sequence.

`start --stage implementation` selects that stage. Optional `--binding primary`
can pin a member of the approved list; it cannot introduce another model or
weaken the frozen risk, quality, data or independence floor. Without an opt-in
list, existing explicit/default behavior remains available. Keep the registry,
host model names, effort, IDs and launch argv local; portable receipts use digests.

Select before adopting an attempt. A changed profile does not change an active
attempt or the current coordinator model. Uncertain dispatch requires reconciliation,
not switching to a reserve. Audit/finalization stage settings still require their
independent lifecycle gates. User-wide defaults are not changed by project setup.

A local proposal does not adopt an attempt. Prepare it with the existing
`start --strategy-out` route, then apply `workflow task-start --strategy` with
its complete current inputs. The later launch checks the exact stored binding
identity. This keeps native task authorization separate from local preferences.

## Probe-only task purpose and source accounting

A project profile selects eligible bindings. It does not select a source-only
accounting exception or change the frozen task purpose. A generic declared source
policy belongs to the reviewed plan's `runtimePolicy.sourceUsageCompletion`.

A frozen task may declare `executionPolicy.availabilityProbeOnly: true`. For that
exact authorized, dependency-ready task, `start --strategy-out` can prepare its
strategy before a positive availability observation exists. This preparation starts
no model and does not adopt the task. It requires an explicit approved binding;
`--launch` is not allowed on this preparation path. Canonical `workflow task-start`
independently checks the strategy and matching risk inputs. A v2 risk profile alone
remains insufficient.

The later explicit `model availability --probe` must use the persisted binding,
operation and attempt. A probe-only task cannot use ordinary managed dispatch, even
after the probe succeeds. The following ordinary task needs fresh availability
before strategy preparation. Changing a local profile or a caller's purpose field
cannot rewrite an active attempt or grant this exception.

See [model routing](model-routing.md#declared-source-completion-when-complete-host-usage-is-unavailable)
for the optional declared source receipt and its limits.

