# Workflow presets

[Русская версия](../ru/reference/workflow-presets.md)

Workflow presets are optional starting configurations for a project workflow.
They make a common route easy to select while keeping the existing project
profile, frozen plan and atomic lifecycle commands authoritative.

## Built-in presets

| Preset | Default mode | Default risk | Review Mesh | Implementation authority |
| --- | --- | --- | --- | --- |
| `quick-change` | `implement` | `S0` | `off` | Frozen plan required |
| `research-review` | `research` | `S1` | `parallel-research-synthesis` | Implementation excluded |
| `feature-implementation` | `implement` | `S2` | `implementation-audit-panel` | Frozen plan required |

The Review Mesh values are existing mode identifiers. Their behaviour remains
advisory unless a frozen plan explicitly enables a blocking gate. Presets do
not contain a provider, model name, account, prompt, secret or executable
command. Quality-floor decisions remain with the existing quality policy and
the plan authority; presets do not store a separate quality field.

The stage limits are versioned preset data:

| Preset | Stages and limits (`attempts` / `invocations` / `seconds`) |
| --- | --- |
| `quick-change` | `implementation` 2 / 8 / 900; `audit` 1 / 4 / 900 |
| `research-review` | `research`, `planning`, `review` 2 / 8 / 1800 |
| `feature-implementation` | `planning` 2 / 8 / 1800; `implementation` 3 / 12 / 3600; `audit` 2 / 8 / 1800 |

`research-review` intentionally has no implementation stage. The other two
presets describe an implementation route, but a preset alone never authorizes
source changes: a frozen plan and its lock are still required.

## Inspect and validate

List the available presets:

```bash
agent-lifecycle project preset list
```

Inspect one complete preset without writing a file:

```bash
agent-lifecycle project preset inspect --preset feature-implementation
```

Validate its contract, limits and security boundary:

```bash
agent-lifecycle project preset validate --preset feature-implementation
```

These commands are deterministic and do not call a model, start a host or
modify the project profile.

## Render a local profile

Render a draft to an explicit path when a team wants the preset values as a
local project profile:

```bash
agent-lifecycle project preset render \
  --preset research-review \
  --adapter <adapter-id> \
  --out .alk/project-profile.json
```

The output is a regular `agent-project-workflow-profile.v1` file. The command
never chooses an implicit path and never overwrites an existing file. The
`.alk/project-profile.json` file is local, ignored by Git and not a project
source-of-truth artifact.

Then check the rendered profile:

```bash
agent-lifecycle project profile check --profile .alk/project-profile.json
```

## Use a preset for one start

For a one-off route, apply a preset without rendering a file:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --preset research-review \
  --text "Study the payment flow and prepare a reviewed implementation plan"
```

The task remains subject to the normal ALK intake, review and freeze rules.
The preset supplies defaults only; it does not start a host when `--launch` is
absent.

## Precedence and advanced control

The effective settings are resolved in this order:

1. mandatory lifecycle and frozen-plan authority;
2. explicit command-line values;
3. explicit project-profile values;
4. preset defaults.

A frozen plan can raise the risk level, require Review Mesh, preserve its write
scope and require its gates. A preset cannot lower any of those requirements.
An explicit project-profile or command-line value can tighten a preset, while a
lower value is rejected when it conflicts with a frozen plan.

Presets do not replace atomic commands. Advanced users can render a profile,
edit only supported local fields, check it against a manifest and lock, and
then continue with the individual lifecycle commands documented in the [CLI
reference](cli.md) and [workflow customization guide](workflow-customization.md).

## Contracts and security

The preset data and operation results use these stable schemas:

- `agent-project-workflow-preset.v1`
- `agent-project-workflow-preset-validation.v1`
- `agent-project-workflow-preset-list.v1`
- `agent-project-workflow-preset-operation.v1`
- `agent-project-workflow-preset-render-receipt.v1`

Preset discovery, validation and rendering are local data operations. Paths
must remain inside the supplied project root, output is write-once, and
provider, model, credential, prompt, URL, executable and sensitive fields are
rejected.
