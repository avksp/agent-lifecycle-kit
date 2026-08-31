# Phase-to-session handoff

Long lifecycle work should cross session boundaries through bounded ALK
artifacts, not by pasting the raw conversation into the next model context.
This recipe reuses existing commands and adds no second session store or
authority path.

## Prepare once

Keep the reviewed manifest, lock, workflow state and compiled task packets in
their declared locations. Create compact plan artifacts for later sessions:

```bash
agent-lifecycle plan snapshot \
  --manifest work/plans/release/plan.manifest.json \
  --out work/release/plan-snapshot.json

agent-lifecycle plan handoff \
  --manifest work/plans/release/plan.manifest.json \
  --snapshot work/release/plan-snapshot.json \
  --lock work/plans/release/plan.lock.json \
  --phase-packet-out work/release/planning-phase-packet.json \
  --max-workstreams 12 \
  --target-tokens 4096 \
  --out work/release/plan-handoff.json
```

These are operator preparation commands. They do not freeze the plan,
authorize execution or accept a task.

## Planning session

Give the planning session the user request, repository references and current
plan package. Its bounded output is the reviewed manifest, review, lock,
snapshot and handoff. Do not carry a raw transcript forward.

Before ending the session, record only structured continuation facts in a
checkpoint input: latest intent, accepted decisions, open blockers, next
required action and digest-bearing artifact references. Then run:

```bash
agent-lifecycle context checkpoint \
  --session planning-session \
  --state work/release/run.state.json \
  --plan work/plans/release/plan.manifest.json \
  --input work/release/planning-checkpoint-input.json \
  --reason planning-complete \
  --capture-mode MILESTONE \
  --adapter <adapter-id> \
  --out work/release/planning-checkpoint-receipt.json
```

## Implementation session

Start from the current workflow state and only the selected compiled task
packet. Restore the checkpoint as a bounded continuation if needed:

```bash
agent-lifecycle context restore \
  --checkpoint .alk/context/checkpoints/<checkpoint-id>.json \
  --state work/release/run.state.json \
  --session planning-session \
  --target-tokens 2048 \
  --out work/release/planning-continuation.json
```

The continuation has `implementationAuthorized: false` and `proofAuthority:
none`. The operator must still use the current authority-bearing workflow
transition, such as `workflow task-start`, with expected state and source
revision. The worker reads its task packet, writes only owned paths, captures a
fresh `workflow task-snapshot`, and submits `workflow task-result`.

A new session can receive a separate bounded implementation packet without
changing the ordinary task-change-set output:

```bash
agent-lifecycle workflow task-snapshot \
  --state work/release/run.state.json \
  --task WS-01 \
  --manifest work/plans/release/plan.manifest.json \
  --lock work/plans/release/plan.lock.json \
  --phase-packet-purpose IMPLEMENTATION \
  --phase-packet-out work/release/WS-01/implementation-phase-packet.json \
  --out work/release/WS-01/task-change-set.json
```

## Independent audit session

Give the reviewer the frozen manifest and lock, task packet, fresh change set,
task result and criterion-specific evidence. Do not give the reviewer the
worker's hidden reasoning or ask it to infer acceptance from a summary. The
reviewer returns a review with its own identity and run id.

After `task-result`, repeat `workflow task-snapshot` with
`--phase-packet-purpose TASK_AUDIT`. ALK projects the immutable change set
bound to the committed result. For a started retry use `REMEDIATION`; the
packet includes prior receipt digests, open finding IDs and remaining attempts.

`workflow task-review-apply`, `workflow task-accept` and `workflow task-rework`
are authority-bearing transitions. An operator invokes them only with a valid,
independent review bound to the current task attempt and source revision.

## Acceptance session

The acceptance session needs current workflow state, the accepted review,
final-audit evidence and compact status, not the earlier raw transcripts. For a
long-running goal, an operator can also request a bounded view:

```bash
agent-lifecycle goal summarize \
  --record work/goal-record.json \
  --state work/goal-state.json \
  --target-window 2048
```

Finish through the current workflow final-audit and finalization commands.
Checkpoints, snapshots, handoffs and summaries remain evidence only; none can
replace a lock, task review, authorization or final proof.

## Required boundaries

- Keep packet, checkpoint and handoff limits from the frozen plan.
- Reject stale plan, state, source revision or task-attempt lineage.
- Keep previous attempt results and reviews immutable during REWORK.
- Store no raw transcript, system prompt, secret or local absolute path.
- Report missing telemetry as unavailable, not zero.
- Do not reduce review, security, architecture or quality gates to fit context.
