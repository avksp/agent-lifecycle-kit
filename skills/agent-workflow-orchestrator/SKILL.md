---
name: agent-workflow-orchestrator
description: Run or resume the full lifecycle from request clarification through reviewed planning, freeze, authorized execution, per-task audits, and final proof.
---

# Agent workflow orchestrator

Use `agent-workflow-orchestrator` to drive the complete lifecycle. The
controller is host-neutral: skills define semantics, while each host adapter
owns native questions, approvals, tool calls, agent launch, waiting,
cancellation, and telemetry.

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

Managed workflow commands may show progress with `--progress-hook stderr` or
write `agent-progress-hook-receipt.v1` with `--progress-hook receipt
--progress-receipt <path>`. Use this only as a display/proof-of-managed-command
layer; installing a plugin or skill is not proof that the lifecycle ran.

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

For common operator requests, route through the cookbook before dropping to
atomic commands: `docs/guides/lifecycle-cookbook.md` covers research-only,
planning-only, Markdown plan review, code review, implementation audit and
cross-review flows. Beginner paths should start from those recipes; advanced
users can continue with the atomic commands listed in the CLI reference.

If a frozen plan opts into Review Mesh, prefer
`agent-lifecycle review-mesh prepare` for common operator flows: it builds a
local profile, reviewer packets and `agent-review-mesh-prepare-receipt.v1`
without launching hosts. Advanced flows may still use atomic
`review-mesh assign`; host adapters or operators run the reviewers, ALK imports
their outputs with `review-mesh import-result`, synthesizes with
`review-mesh synthesize`, and requires `review-mesh quorum` receipts only for
the phases named by the plan. Do not treat Review Mesh as authority to inject
prompts into hosts or bypass review/freeze.

## State rules

- Immutable authority: plan manifest, plan lock, frozen packets.
- Mutable runtime: workflow state, journal, task results, task reviews,
  evidence receipts, final audit.
- Every mutation needs an operation id, expected revision, source revision, and
  reason.
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
