# Project workflow profile

A project workflow profile is a small, project-local defaults file for the
unified ALK start command. It helps a team use the same stage names, default
adapter, risk level, review mode and bounded resource limits without putting
project preferences into the ALK plan.

The profile belongs to the consuming project. It is normally kept in the
ignored `.alk/project-profile.json` path and is not a replacement for a
specification, frozen plan or plan lock.

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
    "modelRoutingProfile": "profiles/model-routing-profile.v1.json",
    "reviewMeshProfile": "profiles/review-mesh-profile.v1.json"
  },
  "stages": {
    "research": {
      "modelClass": "standard-code",
      "reviewMesh": "advisory",
      "maxAttempts": 2,
      "maxWallSeconds": 1800,
      "guidanceRef": "docs/agent-research-guidance.md"
    },
    "implementation": {
      "risk": "S1",
      "reviewMesh": "blocking",
      "maxAttempts": 3
    }
  },
  "productionPromotionClaimed": false
}
```

References stay inside the project root. The `.alk/` exception is reserved for
operator-local host model and launch profiles. The profile loader checks path
components and rejects traversal, absolute paths, URLs and symlink escapes.

## Authority and receipts

The effective order is:

1. mandatory ALK lifecycle rules;
2. the frozen plan and matching lock;
3. the project profile;
4. safe command-line defaults.

A lower layer can fill a default but cannot reduce the plan's risk tier,
quality floor, write scope, required gate or receipt requirement. The profile
digest is carried into the execution strategy and task packet projections.

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
