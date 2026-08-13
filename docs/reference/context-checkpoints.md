# Context checkpoints and compaction recovery

ALK can preserve a compact, typed continuity view when a long host session is
about to be compacted. A checkpoint is a local runtime artifact. It helps the
host restore the current context, while the frozen plan, workflow state and
accepted evidence remain authoritative.

## Capture modes

| Mode | When it is produced | What the status means |
| --- | --- | --- |
| `MILESTONE` | An opted-in ALK workflow transition | ALK created the checkpoint locally at a declared lifecycle event. |
| `AGENT_REQUESTED` | An explicit operator or host request | The caller asked ALK to capture a structured summary. |
| `NATIVE_HOOK` | An adapter supplies accepted pre-compaction event evidence | The adapter, rather than ALK core, observed the host event. |
| `UNAVAILABLE` | No capture route is available | No automatic pre-compaction observation is claimed. |

Guidance or plugin installation does not establish `NATIVE_HOOK`. That mode
requires an accepted adapter capability and a matching neutral event receipt.

## Create a checkpoint

The input is a JSON object containing a bounded summary. It may include current
decisions, constraints, blockers, changed files and the next action. It must not
contain a transcript or authority fields.

```bash
agent-lifecycle context checkpoint \
  --session session-123 \
  --state work/run.state.json \
  --plan tasks/current/plan.manifest.json \
  --input work/context/decisions.json \
  --reason agent-requested \
  --out .alk/context/checkpoints/session-123.json
```

The command writes `agent-context-checkpoint.v1`. It binds the session, run,
plan revision and digest, workflow state revision, source revision and
referenced artifact digests. Secret-like values and private paths are redacted;
prompt, tool, freeze, acceptance and implementation authority fields are
rejected.

For `NATIVE_HOOK`, include a `nativeHookEvidence` object in the input with
`status: PASS`, `accepted: true`, `producerBoundary: adapter-owned`, and the
capability and event receipt digests. ALK stores it as `captureEvidence` and
rejects the checkpoint when the adapter-owned proof is missing or invalid.

## Restore after compaction

```bash
agent-lifecycle context restore \
  --checkpoint .alk/context/checkpoints/session-123.json \
  --state work/run.state.json \
  --session session-123 \
  --out work/context/continuation.json
```

Restore checks the current lineage, digest, redaction state and size limits. On
success it returns `agent-context-continuation.v1`, a bounded packet containing
the summary and references. The packet always carries
`implementationAuthorized: false` and `proofAuthority: none`. A stale or
tampered checkpoint returns a blocked result and does not alter workflow state.

## Milestone policy

A frozen plan may opt in to milestone capture with a bounded policy:

```json
{
  "enabled": true,
  "required": false,
  "milestoneEvents": ["plan-adopted", "task-completed"],
  "maxCheckpointsPerRun": 64,
  "retentionPolicy": "retain-latest-with-explicit-delete"
}
```

The normalized policy is stored when the plan is adopted. The one gate in
`workflow/operation_kernel.commit_state` runs before the state write. Required
capture fails before the transition; optional capture records a non-blocking
failure and preserves the transition. The idempotency key combines operation
identity, state revision and event type, so retrying the same transition does
not create a second checkpoint.

## Storage and security

Checkpoints are stored under `.alk/context/checkpoints`. Writes are atomic and
the store retains at most 64 artifacts per run. Cleanup removes only the oldest
contained checkpoint files. The core performs no model, provider, network,
subprocess or host-CLI calls. A checkpoint is continuity context, not a plan,
review, acceptance receipt or final proof.

## Token and quality impact

Checkpoint creation is deterministic and has no model-token cost. A restored
packet is bounded by the selected continuation budget, which reduces repeated
reading of a long conversation. The compact packet can improve continuity, but
it cannot compensate for missing requirements or weak tests; those remain the
responsibility of the specification, plan and acceptance evidence.

Related pages: [episode retrieval](episode-retrieval.md),
[managed adapter sessions](managed-adapter-sessions.md) and [system
architecture](../architecture/system-architecture.md).
