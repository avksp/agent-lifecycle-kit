# Workflow customization and execution controls

ALK combines a fixed lifecycle controller with a configurable plan for each
task. The controller keeps the meaning of the lifecycle stable; the plan
chooses the workstreams, checks, reviewers and resource limits for the task.

The standard lifecycle is:

```text
task intake -> specification -> plan -> freeze -> execution -> audit -> final proof
```

## Quick answers

| Question | ALK supports | Boundary |
| --- | --- | --- |
| Several agents on one task | Yes. Review Mesh creates separate reviewer packets and binds their results to one plan and task lineage. | Each host run has its own adapter session. ALK does not merge several native chat sessions into one host conversation. |
| A custom workflow | A plan can define workstreams, dependencies, write scope, acceptance criteria, validation commands and optional gates. | The lifecycle state machine and its transition rules are fixed. A new lifecycle state requires a code change. |
| Provider, model and reasoning settings | A host-local profile maps ALK's provider-neutral model class to a concrete host, provider, model and host settings. | Concrete provider and model names stay in host-local configuration, not portable plans or workflow state. |
| Custom prompts | Host skills, wrappers and adapter instructions can define the prompts used by the external agent. | ALK core does not inject, rewrite or inspect a host's system prompt. |
| Timeouts and retries | Run deadlines, task-attempt deadlines, maximum attempts, bounded host-launch timeouts and runner resource caps. | There is no unlimited automatic loop. A limit breach creates a structured block. |
| Optional review cycles | Review Mesh can be advisory or a required gate for phases named by a frozen plan. | It is off by default and the host processes are started outside ALK core. |

## Practical entry points

Use the simple entrypoint when one host is enough:

```bash
agent-lifecycle start --adapter <adapter-id> --file task.md
```

Ask whether independent review is useful without starting any reviewer:

```bash
agent-lifecycle review-mesh recommend \
  --file task.md \
  --out review-mesh-recommendation.json
```

The recommendation is advisory. To run a review panel, prepare assignment
packets, run the selected adapters or host CLIs separately, then import and
synthesize their results. The complete sequence is in the [multi-model review
workflow](../guides/review-mesh-workflow.md).

Resolve a concrete host model only through a local profile:

```bash
agent-lifecycle model route \
  --profile profiles/model-routing-profile.v1.json \
  --host-profile <host-model-profile.json> \
  --request <model-route-request.json>
```

The plan and portable receipts keep the provider-neutral class. The local host
profile supplies the concrete model and reasoning settings. Run and attempt
limits come from the bound plan, runner policy and host-launch profile; they
are not hidden defaults in the prompt.

## Several agents on one task

Several agents can contribute to one ALK task, but they do not share one native
conversation. Each adapter/model binding runs in its own host session. ALK
connects the sessions through the common plan digest, task id, source revision,
assignment and result receipts.

Review Mesh supports three common arrangements:

- one agent prepares a draft and other agents review it;
- several agents research or plan independently and ALK combines the findings;
- several agents audit completed implementation evidence before acceptance.

ALK prepares bounded packets, imports redacted results, synthesizes findings and
can validate a quorum. The operator or host wrapper starts each external agent.
Any available adapter/model combination is valid. A second model is not required
when the task uses the ordinary one-reviewer path.

See [Review Mesh](review-mesh.md) and the [multi-model review workflow](../guides/review-mesh-workflow.md).

## Customizing a workflow

The lifecycle state machine is deliberately stable. Customization happens in a
plan, not by replacing the controller:

- `workstreams` define the task packets and their owners;
- `dependsOn` defines the order between packets;
- `writes` and forbidden paths define the write boundary;
- acceptance and evidence ids define what must be proved;
- validation commands define deterministic checks;
- final-audit and security gates define additional release conditions;
- an optional Review Mesh requirement can be attached to a named phase.

This is enough to make a plan for a small change, an architecture review, a bug
investigation, or a multi-agent implementation. It is not a general-purpose
workflow builder. Adding a new lifecycle state, transition rule or kind of
authority belongs in the ALK code and contracts.

## Provider, model and reasoning selection

ALK resolves a provider-neutral model class such as `budget`, `standard-code` or
`strong-reasoning`. The adapter or host-local model profile maps that class to
the concrete provider, model, context size, tool support and reasoning options
available on the host.

The portable plan records the class and binding digests. Personal provider,
model and account settings remain local to the host. This allows the same plan
to move between adapters without putting a provider choice into the lifecycle
contract.

Prompt text is a host concern. A host skill, wrapper or adapter page may provide
instructions for the external agent. ALK provides bounded task packets and
checks the returned evidence; it does not silently change the host's system
prompt.

See [model routing](model-routing.md), [risk-aware execution](risk-aware-execution.md)
and [adapter usage modes](../adapters/usage-modes.md).

## Timeouts, attempts and retries

ALK uses bounded execution controls at several levels:

- the run can have a maximum wall-clock duration;
- each task attempt can have its own deadline;
- the plan state can cap the number of task attempts;
- a host-launch profile defines a process timeout and a bounded preflight;
- the controlled runner caps attempts, reroutes, splits and resource usage.

When a timeout, failed command, missing usage receipt or resource cap occurs,
the transition returns a structured failure or block. It does not silently
downgrade the policy or continue forever.

Retries are explicit bounded attempts. Their failure signals can cause the
provider-neutral route to escalate to a stronger review class, but a retry does
not change the approved write scope or the plan authority. If the plan needs a
different scope or lifecycle rule, it must be revised and frozen again.

For a detailed attempt loop, see [Controlled runner](runner.md) and [runner
recovery](runner-recovery.md). For host process limits, see [local host
launch](local-host-launch.md).

## Sessions and resume

An ALK session stores lifecycle state and lineage for an adapter. Resume checks
the adapter, plan, source revision and state identity. It does not reconstruct
authority from a native host chat history.

This means a long task can resume safely, while a new host conversation still
has to receive the current bounded packet and the relevant receipts.

See [managed adapter sessions](managed-adapter-sessions.md) and [how ALK works
across different tasks](../guides/how-alk-works.md#resume-work).

## What is deterministic

ALK can deterministically check schemas, digests, plan lineage, write scope,
dependencies, required receipts, resource caps, timeouts and validation results.
The external agent remains responsible for research, code changes and semantic
judgement. Requirements that must be checked without relying on an agent should
be expressed as tests, contracts or other executable validation and linked to
the plan's acceptance criteria.

## Choosing a path

- Use one adapter and one reviewer for ordinary product work.
- Use several adapters or models when the plan needs independent research,
  disputed assumptions or a review quorum.
- Use a host-local model profile when the concrete model, context or reasoning
  settings must be controlled.
- Use explicit task-attempt and run caps when the work is long or expensive.
- Revise and refreeze the plan when the required scope or lifecycle rules change.

Related pages: [quickstart](../guides/quickstart.md), [execution strategy](execution-strategy.md), [source of truth](source-of-truth.md) and [implementation audit](implementation-audit.md).
