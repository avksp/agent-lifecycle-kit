# Optional thread bridge

The optional thread bridge lets an adapter expose host-owned threads or other
harness entities through typed ALK artifacts. It is a transport boundary for
`read`, `list`, `send` and `create`; it is not a second lifecycle controller.

## What the bridge does

The bridge has four explicit steps:

1. ALK prepares a bounded `agent-thread-operation-request.v1`.
2. The adapter checks its declared capability and performs the native host
   operation, if that capability is qualified.
3. The adapter returns an `agent-thread-operation-receipt.v1` with operation
   lineage, status and redaction metadata.
4. ALK validates the exchange and can import the result as
   `agent-thread-context-import.v1`.

The core does not need a provider SDK, network client or host process to build
these artifacts. Native thread identifiers and transport details stay in the
adapter. A capability declaration describes support; a later adapter-specific
qualification receipt establishes usable support.

## Operations and authorization

| Operation | Typical use | Scope | Approval | Receipt requirement |
| --- | --- | --- | --- | --- |
| `read` | Read one selected thread | Explicit target | None | Request and receipt lineage |
| `list` | List bounded project/workflow entities | Project or workflow | None | Bounded result and lineage |
| `send` | Send a message to a selected thread | Explicit target | Operator | Approval and idempotency key |
| `create` | Create a project/workflow entity | Project or workflow | Operator | Approval and idempotency key |

The project profile uses one `threadBridge` policy. It is `off` by default and
can be enabled per operation and lifecycle phase. A frozen plan may require an
operation or narrow its scope and limits. The effective profile applies the
frozen-plan boundary after profile validation.

## Prepare a request

Prepare a read request for an explicitly identified thread:

```bash
agent-lifecycle thread request \
  --operation read \
  --target-hash <thread-reference-hash> \
  --max-tokens 2048 \
  --out work/thread/read-request.json
```

Prepare a bounded list request:

```bash
agent-lifecycle thread request \
  --operation list \
  --scope project \
  --max-tokens 1024 \
  --out work/thread/list-request.json
```

Mutating operations require an operator-approved request and an idempotency
key:

```bash
agent-lifecycle thread request \
  --operation send \
  --target-hash <thread-reference-hash> \
  --text "Please review the attached plan" \
  --idempotency-key send-plan-001 \
  --out work/thread/send-request.json
```

The command prepares JSON only. The adapter reads the request, performs the
host-owned action and writes the receipt in its own integration boundary.

## Import a receipt

Import a validated adapter response as optional context:

```bash
agent-lifecycle thread import \
  --request work/thread/read-request.json \
  --receipt work/thread/read-receipt.json \
  --source-id selected-thread \
  --out work/thread/context.json
```

The imported artifact records its source digest, redaction status and resource
caps. Its content is useful for restoring context or preparing a reviewer
packet. It is explicitly not a specification, plan, acceptance evidence or
final proof. The receipt marks it with `sourceOfTruth: false` and `proof: false`.

## Use with Review Mesh and context continuity

Thread context can be added to an existing episode-retrieval query or projected
into a Review Mesh packet as the `optional-thread-context` source role. Review
Mesh still owns reviewer assignments, result import, synthesis and quorum;
thread operations only transport the selected context.

Context checkpoints remain the preferred continuity artifact for a long ALK
run. A thread import can inform a checkpoint, but it cannot change its plan
lineage or grant implementation authority. See [context checkpoints](context-checkpoints.md)
and [Review Mesh](review-mesh.md).

## Project policy example

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

The bridge remains optional. Projects that do not declare it continue through
the ordinary ALK lifecycle without a thread operation.
