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

Managed commands may show progress with `--progress-hook stderr` or write
`agent-progress-hook-receipt.v1` with `--progress-hook receipt
--progress-receipt <path>`. This is display/proof only; plugin or skill
installation is not lifecycle proof.

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

For optional host-thread coordination, prepare bounded `read`, `list`, `send`
or `create` requests with `agent-lifecycle thread request`, then import the
adapter-owned receipt with `agent-lifecycle thread import`. The bridge is off by
default; `send` and `create` require approval and an idempotency key. Imported
content is advisory and cannot replace a frozen plan, acceptance evidence or
Review Mesh quorum.

Inspect a declaration with `agent-lifecycle adapter thread-capability` and
validate its receipt with `agent-lifecycle adapter thread-qualify`. Only a
matching receipt projects `capability_support="supported"`. These commands are
inspection-only; core
does not launch or contact a host.

For a project-wide default adapter and bounded stage settings, initialize or
check the consuming project's local profile with `agent-lifecycle project
profile init/check`. When `.alk/project-profile.json` is present, `start` may
omit `--adapter`; use `--project-profile <path>` for explicit selection and
`--no-project-profile` for a run without local defaults. Treat the profile as a
defaults layer only: the frozen plan and matching lock remain authoritative for
risk, quality, write scope, gates and receipts.

When the operator adds `--launch` to raw `auto`, `research`, `plan` or `review`
input, launch only an exact-version qualified planning-only profile. Resolve
the default profile from `.alk/host-launch/<adapter>.json`, carry the task over
bounded stdin, and end in `REVIEW_REQUIRED` or `BLOCKED`. A missing or stale
profile must return preparation and preflight commands. Persist only digest
lineage below `.alk/planning-sessions`; `--resume` may read that state but must
not reattach or relaunch a native host conversation. Implementation remains a
separate process using a reviewed frozen manifest, matching lock and complete
workflow bindings.

When a frozen task requests risk-aware execution, keep the authorization split.
Run `agent-lifecycle start --risk <auto|S0|S1|S2> --risk-profile-out <path>` to
project the digest-bound route and caps without changing workflow state. Then
pass that exact artifact to `workflow task-start --risk-profile <path>` with
the same operation and lineage bindings. Do not claim a risk-aware attempt from
raw intake or from `start` alone. Before accepting its result, require
host-attested tokens, `usage.invocations`, and wall time within all bound caps.

For common requests, use `docs/guides/lifecycle-cookbook.md` for research-only,
planning, Markdown plan review, code review, implementation audit and
cross-review. Beginners start there; advanced users can use atomic commands.

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
