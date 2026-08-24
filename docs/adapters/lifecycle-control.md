# Optional adapter lifecycle control

Release 1.80 adds an optional control boundary between a host adapter and the
ALK workflow. It helps a host check whether an observable action belongs to
the frozen plan and whether the resulting evidence is complete. It does not
control the model's private reasoning and it does not replace host approvals,
sandboxing or human review.

## Assurance levels

The level is recorded separately for every adapter operation:

| Level | Meaning |
| --- | --- |
| `GUIDANCE_ONLY` | The host skill or page tells the model how to follow ALK. No prevention or observation claim is made. |
| `OBSERVED` | A qualified host-owned producer records the action. It cannot prevent the action, but missing or altered evidence can block acceptance. |
| `ENFORCED` | A qualified host-owned pre-action boundary blocks the action before execution and the post-action and stop checks bind the result to ALK state. |

Each operation publishes `declaredLevel`, `supportedLevel`,
`qualifiedLevel` and `qualificationStatus`. A declaration never promotes an
operation. The strongest published level is the strongest level reproduced by
the corresponding evidence for the exact host version.

The bundled adapters currently publish `GUIDANCE_ONLY` and
`NO_RECOMMENDATION` for lifecycle-control operations. Their managed launch
status remains `WRAPPER_ONLY`. This is an explicit support statement, not an
error: native host qualification requires an operator-controlled live matrix.

## What ALK checks

The optional boundary covers four ALK operations:

- `file-edit` and `shell-command` before and after an observable action;
- `task-accept` before accepting a task result;
- `run-finalize` before final proof is accepted.

The pre-action decision binds the operation to the plan digest, lock digest,
state revision, task, action digest and normalized paths. The post-action check
compares actual changed paths and command status with that decision. The stop
check requires the existing task acceptance and final proof contracts.

Control is off or guidance-only by default. A host must own the blocking
boundary and keep its configuration and any attestation key outside the
model-writable repository scope. Missing ALK, timeout, malformed output,
disabled control or producer termination cannot support an `ENFORCED` claim.

## Local checks

Validate the bundled policy and portable evidence without starting a host:

```bash
agent-lifecycle adapter lifecycle-control-check \
  --policy policy/adapter-lifecycle-control.json

agent-lifecycle adapter event-check \
  --event <adapter-event-1.json> \
  --event <adapter-event-2.json>
```

The command returns structured JSON. `PASS` means the supplied contract is
valid; `REVIEW_REQUIRED` identifies evidence that needs a decision; `BLOCKED`
means the selected control cannot safely continue. A successful text response
from a host is not lifecycle proof.

## Inside a host and from the terminal

Inside a host, install the adapter's skill or plugin and explicitly request
`agent-workflow-orchestrator`. The host remains responsible for the model,
tools and approvals. Use the terminal route when the host has no integration
or when reproducible command evidence is preferred:

```bash
agent-lifecycle start --adapter <adapter-id> --file task.md
```

Both routes use the same ALK plan, state, ownership and evidence contracts.
The difference is who invokes the host: the interactive adapter session or the
`agent-lifecycle` command. See [Using ALK with an adapter](usage-modes.md).

## Evidence and limits

Lifecycle-control evidence uses bounded, redacted contracts such as
`agent-lifecycle-control-request.v1`,
`agent-lifecycle-control-decision.v1`,
`agent-lifecycle-control-event.v1` and
`agent-lifecycle-control-qualification.v1`. It stores digests, statuses,
paths and bounded metadata, not prompts, transcripts, secrets or unrestricted
environment values.

Qualification is operation-specific and exact-version. Offline fixtures prove
contract behavior only. They cannot promote an adapter to `OBSERVED` or
`ENFORCED`; unavailable live evidence remains `NO_RECOMMENDATION`.

## Action evidence and effective configuration

Release 1.87 attaches a bounded action-evidence envelope to the existing event
stream. It binds the ALK request and operation to the profile, effective
configuration, capability declaration, permission decision and safe result
link. The envelope contains digests and bounded categories; it never stores raw
prompts, model reasoning, credentials or local absolute paths.

Use `agent-lifecycle project profile explain` to inspect the selected value and
its `winningSource`, `overriddenSources`, `planConstraint` and enforceability.
Frozen-plan authority constrains risk, mandatory review and thread bridge; it is
not a generic last-write-wins configuration layer. Missing or stale capability
lineage yields `UNAVAILABLE` and cannot promote an adapter claim.

See [adapter action evidence](../reference/adapter-action-evidence.md) and
[effective configuration](../reference/effective-configuration.md).

See also [Adapter support matrix](support-matrix.md),
[Adapter event capture](../reference/adapter-event-capture.md),
[Managed lifecycle runner](../reference/managed-lifecycle-runner.md) and
[System architecture](../architecture/system-architecture.md).
