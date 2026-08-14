# Beginner and advanced workflows

[Русская версия](../ru/guides/beginner-and-advanced-workflows.md)

ALK has one simple entry point for a normal task and separate commands for
operators who need exact control. Both paths use the same plan, evidence and
acceptance rules.

## Beginner path

1. Install ALK by following [Install ALK and make the first run](install-and-first-run.md).
2. Check the available routes:

   ```bash
   agent-lifecycle project preset list
   ```

3. Start with a task file or text. Choose the adapter that is installed on the
   machine:

   ```bash
   agent-lifecycle start --adapter <adapter-id> --preset research-review --file task.md
   ```

   or:

   ```bash
   agent-lifecycle start --adapter <adapter-id> --text "Investigate the cache failure and prepare a reviewed plan"
   ```

4. Read the JSON receipt. Raw text, research and planning remain reviewable
   until a plan is approved and frozen. A preset only supplies bounded defaults;
   it does not start a host or authorize source changes.

Use `quick-change` for a small planned change, `research-review` for research
and a reviewed plan, and `feature-implementation` when the task already has a
route through planning, implementation and audit. The full preset matrix is in
[Workflow presets](../reference/workflow-presets.md).

## Advanced path

Use atomic commands when the team needs to inspect or control each lifecycle
step. A reusable local setup is described in [Project workflow profile](../reference/project-workflow-profile.md):

```bash
agent-lifecycle project preset inspect --preset feature-implementation
agent-lifecycle project preset validate --preset feature-implementation
agent-lifecycle project preset render \
  --preset feature-implementation \
  --adapter <adapter-id> \
  --out .alk/project-profile.json
agent-lifecycle project profile check --profile .alk/project-profile.json
```

Then use the plan, task, strategy, workflow and audit commands from the [CLI
reference](../reference/cli.md). Use the [workflow customization guide](../reference/workflow-customization.md)
to set model classes, host-local model bindings, prompts, timeouts and retry
limits. Use [Review Mesh](review-mesh-workflow.md) when independent agents or
models should research, review or audit the same plan without sharing a native
host conversation.

The advanced path can pass `--no-project-profile`, bind an explicit manifest
and lock, compile task packets, and require implementation or final audits.
The frozen plan remains the authority for risk, write scope, required gates and
accepted evidence.

## Choosing a route

Start with the beginner path when one adapter and one reviewed task are enough.
Use the advanced path when the project needs a reusable local profile, several
reviewers, explicit model routing, phase limits or a handoff between operators.
The route can be changed later by updating and refreezing the plan when its
scope or lifecycle requirements change.
