# Small-model packets

Small-model packets shrink the execution surface for local or compact models
without weakening the lifecycle. They are compiled from frozen
`agent-task-packet.v1` packets and keep the same plan digest, acceptance ids,
evidence ids and write-scope authority.

Use them when a task is suitable for a small execution surface:

- one task per packet;
- exact write scope and forbidden paths;
- compact context receipt for the selected 4k/8k/16k window;
- required output contract;
- explicit validation commands or validation ids;
- forbidden actions such as expanding write scope or claiming final audit.

```bash
agent-lifecycle task compile-small \
  --manifest <plan.manifest.json> \
  --context-profile profiles/small-context-profile.v1.json \
  --target-window 4k-strict \
  --write
```

The command emits `agent-small-model-packet-compile-result.v1`. Written packets
use `agent-small-model-task-packet.v1`; their index uses
`agent-small-model-task-packet-index.v1`.

## Output contract

Each small-model packet carries `agent-small-model-output-contract.v1`. The
worker must answer with `agent-small-model-task-result.v1` and include:

- `status`;
- `taskId`;
- `changedFiles`;
- `validation`;
- `summary`;
- `blockers`;
- `writeScopeDigest`;
- `outputContractDigest`;
- `productionPromotionClaimed: false`.

`agent-small-model-output-validation.v1` fails closed when required fields are
missing, the task id differs, changed files leave the write scope, digest
bindings drift, or production promotion is claimed.

## Adaptive policy

Small-model packets are an execution surface, not a lower quality mode. When an
adaptive lifecycle decision is supplied, packet selection is allowed only when
the quality floor permits it. Strict and release floors block automatic
small-model packet selection; those tasks need a stronger route, explicit
split/refreeze, or a reviewed override outside the portable default.

## Context

The compiler renders compact context before accepting a packet. Overflow fails
closed; truncation is not allowed. A small packet can be passed back to
`agent-lifecycle context check/render`, which projects only the active task,
write scope and output contract digest.

Small packets do not satisfy critical review, security review, final audit or
production promotion by themselves. Those phases still require calibrated
review-capable routes and the normal lifecycle evidence.
