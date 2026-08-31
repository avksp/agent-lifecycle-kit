# Phase packets

Phase packets are bounded, purpose-specific projections for moving exact facts
between model sessions. They reduce repeated context loading without creating a
second workflow state or a second authority path.

The envelope schema is `agent-phase-packet.v1`. Its purpose is one of:

- `PLANNING_HANDOFF` for selected workstreams and dependency edges;
- `IMPLEMENTATION` for one task attempt, scope, criteria and evidence;
- `TASK_AUDIT` for the committed result, immutable change set and review facts;
- `REMEDIATION` for the prior result/review, open findings and retry budget.

Every packet is bound to the current plan, lock, source revision and relevant
state revision. It also binds write scope, acceptance, evidence and active
blockers with canonical digests. The rendered envelope is limited to 64 KiB.
Required facts are never dropped to satisfy that limit.

## Create packets

Planning handoff keeps its existing output and writes the optional packet to a
separate path:

```bash
agent-lifecycle plan handoff \
  --manifest <plan.manifest.json> \
  --snapshot <plan-snapshot.json> \
  --lock <plan.lock.json> \
  --phase-packet-out <planning-phase-packet.json> \
  --out <plan-handoff.json>
```

Task packets are additional outputs of the read-only task snapshot route:

```bash
agent-lifecycle workflow task-snapshot \
  --state <run.state.json> \
  --task <task-id> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --phase-packet-purpose IMPLEMENTATION \
  --phase-packet-out <implementation-phase-packet.json> \
  --out <task-change-set.json>
```

The four packet-specific task-snapshot options are all-or-none. Use
`TASK_AUDIT` after a result is committed and `REMEDIATION` for a started retry.
The ordinary handoff and task-change-set JSON remain unchanged when packet
options are omitted.

## Safety boundary

Payloads are closed and recursively reject transcripts, prompts, credentials,
cookies, secrets and authority-like fields. String values pass through the
existing path and secret redaction controls. Failures use stable codes:

- `phase-packet-required-fact-missing`;
- `phase-packet-forbidden-content`;
- `phase-packet-context-limit-exceeded`.

Every envelope has `implementationAuthorized: false`, `proofAuthority: none`
and `productionPromotionClaimed: false`. A packet cannot start work, accept a
task, freeze a plan, satisfy a review or promote a release. The current lock,
workflow state and normal authority-bearing transitions remain authoritative.

