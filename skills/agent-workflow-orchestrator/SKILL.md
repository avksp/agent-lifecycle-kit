---
name: agent-workflow-orchestrator
description: Run or resume the full lifecycle from request clarification through reviewed planning, freeze, authorized execution, per-task audits, and final proof.
---

# Agent workflow orchestrator

Drive the complete lifecycle with this skill. The controller is host-neutral:
skills define semantics; adapters own native
questions, approvals, tools, launch, waiting, cancellation and telemetry.

## Lifecycle

1. Load existing durable state when present. Do not reconstruct authority from
   chat.
2. Clarify only decisions that materially change behavior, scope, safety,
   architecture, ownership, evidence, or external authority.
3. Route planning to `agent-first-planning`.
4. Route every candidate specification or plan to independent review through
   `audit-agent-plan`; refine until the freeze verdict passes or blocks.
5. Freeze only reviewed matching inputs.
6. Compile packets with `agent-plan-to-workers`.
7. Respect execution mode: plan-only, approval-required, or auto-after-freeze.
8. Launch only dependency-ready packets within frozen parallelism.
9. Run controller-owned validation before launch and after attempts when the
   plan requires it.
10. Audit every task attempt with `audit-plan-implementation` before
    acceptance.
11. Route implementation/test/evidence defects to bounded remediation. Route
    plan gaps, write-set gaps, architecture changes, or contract changes to
    reopen and refreeze.
12. After all required tasks are accepted, run final implementation audit and
    publish completion only from a reproducible proof.

For remediation require a frozen retry budget, independent `REWORK` evidence
and open finding IDs; in v4 use `workflow task-review-apply` (with
`task-rework` as compatibility wrapper). Never edit state manually.
Before each `task-result`, put a current `workflow task-snapshot` claim in the
result. Later code changes require a new claim and result.

For adapter-backed work, prefer `agent-lifecycle start --adapter <id>` as the
operator-facing entrypoint. It requires exactly one task source or `--resume
<session-id>`. Raw `--file`/`--task-file` and `--text`/`--task-text` inputs in
`auto`, `research`, `plan` or `review` mode create reviewed draft intake only;
they do not claim lifecycle coverage or start implementation. Surface the
receipt's review recommendation as advice and require operator or reviewed-plan
confirmation before treating multi-review as mandatory evidence. Only explicit
`--mode implement` may consume a fully bound frozen request and delegate to the
existing managed run path. `--resume` accepts only stored ALK session identity;
it must never guess a native host conversation id. Use `adapter task start`,
`adapter run` and `adapter session resume` as lower-level commands, and use
`adapter session start` only to record an interactive `WAITING_FOR_TASK`
session. Native host launching remains descriptor-driven and host-owned.

The optional thread bridge is off by default; imported content is advisory and
only matching qualification evidence can project support.

## Adapter lifecycle control

Inspect the operation declaration and capability manifest before an adapter
action. The levels have different guarantees:

- `GUIDANCE_ONLY` gives instructions and does not block a host action.
- `OBSERVED` records a result for later acceptance, but cannot prove prevention.
- `ENFORCED` requires an exact host-owned pre-action boundary and matching live
  qualification for that operation and host version.
- `NO_RECOMMENDATION` means evidence is insufficient for promotion.

Evidence cannot be promoted from a prompt, skill or fixture alone. The selected
level must match adapter-owned evidence and the frozen plan.

For every controlled action, check the frozen plan and lock, state revision,
ownership-safe paths and the pre-action decision before the host call. Bind the
post-action result and changed paths to the same operation, then run task-
acceptance and stop gates. A missing, stale or mismatched receipt blocks the
level selected by the plan.

Project defaults use `agent-lifecycle project profile init/check`. A local
`.alk/project-profile.json` may supply `--adapter`; use `--project-profile` for
an explicit file or `--no-project-profile` to disable defaults. The frozen plan
and lock remain authoritative for risk, quality, scope, gates and receipts.

With `--launch` on raw planning input, use only an exact-version qualified
planning profile from `.alk/host-launch/<adapter>.json`, bounded stdin, and a
`REVIEW_REQUIRED` or `BLOCKED` result. Missing or stale profiles return
preparation commands. Persist digest lineage only; `--resume` must not attach
to a native host conversation. Implementation uses a reviewed frozen manifest,
matching lock and complete workflow bindings.

For risk-aware execution, project the digest-bound route with `start --risk`
and pass that exact profile to `workflow task-start --risk-profile` with the
same operation and lineage. Require host-attested tokens, invocation count and
wall time within all caps before acceptance.

For common requests, use `docs/guides/lifecycle-cookbook.md` for research-only,
planning, Markdown plan review, code review, implementation audit and
cross-review. Beginners start there; advanced users can use atomic commands.

If a frozen plan opts into Review Mesh, use `review-mesh prepare`, then let
adapters run reviewers and import, synthesize and quorum receipts. Review Mesh
is not authority to inject prompts into hosts or bypass review/freeze.

## State rules

- Immutable authority: plan manifest, plan lock, frozen packets.
- Mutable runtime: workflow state, journal, task results, task reviews,
  evidence receipts, final audit.
- Every mutation needs an operation id, expected revision, source revision, and
  reason.
- New runs use `agent-workflow-state.v4` from `workflow init`; v3 is accepted
  only through explicit fail-closed `workflow state-migrate`.
- Review, remediation, `CONTRACT_CHANGE` and `BLOCKED` are task-local. The run
  stays `RUNNING` until every required task is `ACCEPTED`, then enters
  `FINAL_AUDIT`.
- Bounded waits only. On timeout, request cancellation through the host adapter
  and record a conservative block.
- Budget exhaustion, missing receipts, stale evidence, or unverifiable
  telemetry cannot produce a pass.

## Context policy

- Keep the latest user instructions and active packet verbatim.
- Summarize older context into structured state.
- Drop tool dumps and intermediate data after extracting decisions, evidence
  ids, hashes, exit codes, and blockers.
- Prefer deterministic validators before semantic review.
- For 4k-strict/8k/16k/32k/64k hosts, render/check context with
  `small-context-profile.v1`; overflow must split, request larger context, or
  block, never silently truncate.

## Output

Return the next typed action, current run phase, locked tasks, active blockers,
accepted evidence, remaining budget, and concrete next command or host action.
When progress hooks are enabled, keep stdout JSON unchanged and treat stderr or
the hook receipt as display evidence only.

## Context continuity

When a host session is long or a compaction boundary is expected, use the
context checkpoint contract instead of relying on memory in the chat. Prefer an
ALK milestone checkpoint when the frozen plan opts into one. Use an explicit
`agent-lifecycle context checkpoint` request when the operator needs to record
decisions immediately. Treat `NATIVE_HOOK` as valid only when the adapter has
supplied accepted event evidence; otherwise keep the support level explicit as
`MILESTONE`, `AGENT_REQUESTED` or `UNAVAILABLE`.

After compaction, restore one bounded continuation packet and re-check its
lineage against the current state. The packet is advisory context only: the
frozen plan, workflow state, ownership rules and accepted evidence remain the
authority for execution and acceptance.
