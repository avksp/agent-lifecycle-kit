# Review Mesh: multi-model review

Review Mesh is an optional contract layer for checking the same bounded
artifact with several independent AI models. Each reviewer can use a different adapter/model binding.
It is useful when a plan wants more than one independent view on planning,
research or implementation evidence, but it is not part of the default lifecycle.

The adapters and models are unrestricted by product name: any available bindings may participate.
The built-in operator templates require independence
on both `host` and `model`. Multiple sessions of one model can be advisory, but
cannot satisfy that model-independence requirement.

The supported mode ids are:

- `leader-draft-multi-review`: one lead creates a draft plan or research result
  and independent reviewers check it.
- `parallel-research-synthesis`: several reviewers prepare independent
  research or plan candidates before synthesis.
- `implementation-audit-panel`: several auditors review implementation
  evidence after work is complete.

Release 1.41 added deterministic recommendation advice. Release 1.42 adds the
semi-automatic layer around it: assignment packets, reviewer result import,
synthesis and quorum validation. ALK still does not run reviewer adapters; the
operator or host wrapper runs them and returns evidence for import.

Release 1.46 adds operator templates and `review-mesh prepare`. The command
turns a task intake receipt, plan manifest or handoff into a local profile,
assignment packets and `agent-review-mesh-prepare-receipt.v1`. It still does
not start reviewers.

## Stable schemas

- `agent-review-mesh-profile.v1`
- `agent-review-mesh-assignment.v1`
- `agent-review-mesh-result.v1`
- `agent-review-mesh-synthesis.v1`
- `agent-review-mesh-quorum-receipt.v1`
- `agent-review-mesh-quorum-validation.v1`
- `agent-review-mesh-recommendation.v1`

## Recommendation advisor

Use the advisor when the operator wants to know whether extra review is worth
the cost before accepting it into a plan:

```bash
agent-lifecycle review-mesh recommend --text "Research the architecture and write a plan"
agent-lifecycle review-mesh recommend --file task.md
agent-lifecycle review-mesh recommend --intake adapter-task-start.json
agent-lifecycle review-mesh recommend --manifest plan.manifest.json
```

The receipt can recommend `off`, `leader-draft-multi-review`,
`parallel-research-synthesis` or `implementation-audit-panel`. It records
phase coverage, reasons, required reviewer count, token/resource caps,
provider-neutral model class hints and a skip rationale when `off` is enough.

The recommendation is not execution authority. It does not activate blocking
gates, create assignments, enforce quorum, start model calls or launch host
CLIs. A reviewed frozen plan must opt in before Review Mesh can become required
evidence. It does not recommend bypassing review/freeze or asking ALK core to
launch adapters.

## Operator templates and prepare

Use `template-list` to see the built-in local templates:

```bash
agent-lifecycle review-mesh template-list
```

The current templates are:

- `leader-draft-review`: prepare plan-review packets for a lead draft.
- `parallel-research-synthesis`: prepare independent research packets before
  synthesis.
- `implementation-audit-panel`: prepare implementation-audit packets after
  task evidence exists.

Use `prepare` when you want ALK to create the profile and assignments in one
step:

```bash
agent-lifecycle review-mesh prepare \
  --intake intake.json \
  --template parallel-research-synthesis \
  --reviewer codex-example:architecture-reviewer:strong-reasoning \
  --reviewer claude-example:risk-reviewer:strong-reasoning \
  --reviewer opencode-glm-example:local-reviewer:local-strong-review \
  --out-dir work/review-mesh/plan-review \
  --out work/review-mesh/prepare-receipt.json
```

The reviewer ids are examples. Concrete model selection stays in the selected
CLI, such as Codex, Claude Code or OpenCode. In the portable ALK receipt, use
provider-neutral model classes such as `strong-reasoning` and
`local-strong-review`.

`prepare` writes `profile.json`, one packet per reviewer under `assignments/`,
and a receipt with `hostExecutionStarted: false`, `modelCallsStarted: false`
and `providerBrokerStarted: false`.

## Assignments, results, synthesis and quorum

After a reviewed plan opts in, ALK can coordinate Review Mesh evidence without
becoming a model broker:

```bash
agent-lifecycle review-mesh profile --profile-id rm-profile --out rm-profile.json

agent-lifecycle review-mesh assign --intake adapter-task-start.json \
  --profile rm-profile.json \
  --mode leader-draft-multi-review --phase plan-review \
  --assignment-id RM-1 --reviewer-id claude-reviewer --out rm-assignment.json

agent-lifecycle review-mesh import-result --profile rm-profile.json \
  --assignment rm-assignment.json --reviewer-output reviewer-output.json \
  --out rm-result.json

agent-lifecycle review-mesh synthesize --profile rm-profile.json \
  --result rm-result-a.json --result rm-result-b.json --out rm-synthesis.json

agent-lifecycle review-mesh quorum --profile rm-profile.json \
  --synthesis rm-synthesis.json --min-reviewers 2 --out rm-quorum.json
```

Assignments are compact packets for host-owned reviewer execution. Imported
results redact secret-like markers and reject local absolute paths unless the
plan explicitly allows local evidence references. Synthesis records agreement,
conflicts, accepted findings, rejected findings and unresolved findings.
Quorum receipts can block freeze, implementation audit or final audit only when
the frozen plan declares Review Mesh as required for that phase.

For command-by-command examples for common tasks, see the
[Review Mesh workflow scenarios](../guides/review-mesh-workflow.md).

## Contract rules

Review Mesh is fail-closed and provider-neutral:

- disabled by default;
- enabled only by an explicit reviewed plan;
- advisory unless the frozen plan opts into blocking use;
- budgeted by tokens, invocation count and wall-clock resources;
- not a canonical USD-cost surface;
- independent by neutral `hostIdentityHash` and `modelIdentityHash` values;
- concrete provider, model and account names are not portable identity fields.

The implementation reuses the existing optional cross-check semantics for
budget caps and independence evidence. Review Mesh adds lifecycle-specific mode
ids and receipts around those checks rather than creating a second review
engine.

## Boundaries

Review Mesh does not bypass specification review, plan freeze, implementation
audit or final proof. It can add evidence only when a task or plan asks for it.
Host CLIs, provider credentials, model selection and reviewer execution remain
adapter-owned or operator-owned.

Review Mesh is never mandatory by installation or by task wording. It becomes
mandatory only when a reviewed frozen plan explicitly requires blocking quorum
for a named phase. Without other models, leave it off or use ordinary
single-reviewer advice. If a frozen plan already requires independent quorum,
the missing capacity is a blocker until the plan is revised and refrozen.
