# Quality-preserving execution strategy

The execution strategy combines existing ALK decisions into one bounded,
provider-neutral receipt. It helps an operator answer four questions without
running a model or changing workflow state:

1. Which quality floor and risk tier apply?
2. Which neutral model class is suitable for each phase?
3. May the implementation task use a compact packet?
4. Which review mode and resource evidence are required?

The strategy is an explanation and a handoff artifact. It cannot freeze a
plan, authorize implementation, start a host, accept a task, or finalize a run.

## Beginner path

Continue to use the unified command:

```bash
agent-lifecycle start --adapter codex --mode plan --file task.md
```

Raw text and Markdown have no frozen execution authority. Their
`agent-lifecycle-start-receipt.v1` therefore contains:

```json
{
  "executionStrategy": {
    "status": "DEFERRED_UNTIL_FREEZE",
    "reason": "frozen-plan-required",
    "advisoryOnly": true
  }
}
```

After a reviewed, frozen run is supplied to `start --mode implement`, the same
field becomes a compact summary bound to the exact plan, task, operation,
state revision, adapter and source revision. Existing review and task-start
gates still control execution.

## Full strategy receipt

Advanced operators can write the complete `agent-execution-strategy.v1`
receipt:

```bash
agent-lifecycle strategy resolve \
  --manifest tasks/my-release/plan.manifest.json \
  --lock tasks/my-release/plan.lock.json \
  --state work/my-release/run.state.json \
  --task WS-01 \
  --operation-id strategy-WS-01 \
  --expected-revision 3 \
  --source-revision "$(git rev-parse HEAD)" \
  --adapter codex \
  --host-model-profile profiles/hosts/codex-live-profile.v1.json \
  --out work/my-release/WS-01/execution-strategy.json
```

The output path is write-once. S1 and S2 need a host-local model profile so
the neutral class can be checked against installed host capabilities. Concrete
provider and model names remain in that local profile and do not enter the
portable strategy.

The receipt includes:

- exact lineage and source-decision digests;
- resolved risk tier, quality floor and selected lifecycle mode;
- phase routes for deterministic validation, implementation and audits;
- full or compact packet mode;
- Review Mesh recommendation or skip rationale;
- token, invocation and wall-time caps;
- required usage confidence;
- explicit non-authority and zero-side-effect fields.

## Task-packet projection

Pass the validated strategy to the regular compiler:

```bash
agent-lifecycle task compile \
  --manifest tasks/my-release/plan.manifest.json \
  --strategy work/my-release/WS-01/execution-strategy.json \
  --write
```

Only the packet for the bound task receives a compact projection. Plan digest,
write scope, acceptance criteria, validation and output authority still come
from the frozen plan.

For an eligible low-risk task:

```bash
agent-lifecycle task compile-small \
  --manifest tasks/my-release/plan.manifest.json \
  --strategy work/my-release/WS-01/execution-strategy.json \
  --context-profile profiles/small-context-profile.v1.json \
  --target-window 4k-strict \
  --write
```

Strict, release and protected S2 strategies fail closed on the compact path.
Use the full packet or split and refreeze the work; do not lower the tier.

## Large and local models

ALK routes by capability class, not product name:

| Work shape | Safe default |
| --- | --- |
| Deterministic schema and release checks | No model. |
| Bounded S0 task with an eligible compact contract | Small or local model through a compact packet. |
| S1 implementation | Standard coding class with usage evidence. |
| S2, architecture or security implementation | Full packet and a strong reasoning class. |
| Independent implementation or final audit | Review-capable class; optional multi-review only when the plan opts in. |

A large model does not bypass gates. A small model receives less context only
when the same authority can be represented without omission.

## Proving an optimization

Evaluate baseline and candidate artifacts first, then compare the receipts:

```bash
agent-lifecycle benchmark compare \
  --baseline work/benchmark/baseline-evaluation.json \
  --candidate work/benchmark/candidate-evaluation.json \
  --out work/benchmark/comparison.json
```

Quality is checked before resource savings. A new false acceptance, lost oracle
check or lineage mismatch fails the comparison. Estimated tokens remain
advisory. Automatic adoption eligibility additionally requires:

- comparable host-attested token usage;
- actual token savings;
- no observed increase in invocations, retries, remediation loops or elapsed
  time;
- no measurement gaps.

The receipt does not mutate policy automatically. It is evidence for a later
reviewed policy or plan change.

## Architecture boundary

`policy/execution_strategy.py` composes the existing quality-floor,
risk-execution, adaptive-lifecycle, model-routing, Review Mesh and compact
packet decisions. Those lower-level modules do not import the strategy layer.
The core contains no provider API, subprocess launch or hidden validation
cache.

Related references:

- [Risk-aware execution](risk-aware-execution.md)
- [Small-model packets](small-model-packets.md)
- [Reference task evaluation](reference-task-evaluation.md)
- [Model routing](model-routing.md)
- [System architecture](../architecture/system-architecture.md)
