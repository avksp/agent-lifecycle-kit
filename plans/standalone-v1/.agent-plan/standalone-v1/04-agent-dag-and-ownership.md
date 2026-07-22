# Agent DAG And Ownership

## Worker Matrix

| Task | Owner | Writable roots | Independent reviewer |
| --- | --- | --- | --- |
| WS-01 | neutrality | package lock/shell, neutrality contract/policy/core/tests/workflow, task evidence | neutrality-reviewer |
| WS-02 | contracts | public contracts, schemas, host protocol and contract tests, task evidence | contracts-reviewer |
| WS-03 | planning | specification/planning/review/freeze services and tests, task evidence | planning-reviewer |
| WS-04 | compiler | task compiler and tests, task evidence | compiler-reviewer |
| WS-05 | workflow | durable workflow/usage/resource services and tests, task evidence | workflow-reviewer |
| WS-06 | audit | audit/change-set services and tests, task evidence | audit-reviewer |
| WS-07 | cli | CLI composition, entry point and tests, task evidence | cli-reviewer |
| WS-08 | skills | exactly five skill roots and skill tests, task evidence | skills-reviewer |
| WS-09 | conformance | synthetic conformance/fixtures/evals and tests, task evidence | conformance-reviewer |
| WS-10 | adapter-worker-a | First surface adapter/conformance/tests, task evidence | adapter-reviewer-a |
| WS-11 | adapter-worker-b | Second surface adapter/conformance/tests, task evidence | adapter-reviewer-b |
| WS-12 | adapter-worker-c | Third surface adapter/conformance/tests, task evidence | adapter-reviewer-c |
| WS-13 | adapter-worker-d | Fourth surface adapter/conformance/tests, task evidence | adapter-reviewer-d |
| WS-14 | release | governance/docs/release tooling/CI/tests, task evidence | release-reviewer |
| WS-15 | final-auditor | final evidence only | lead-final-reviewer |

Exact repository-relative write paths and worker ceilings are frozen in
`plan.manifest.json`. Directories imply recursive ownership. No two executable
tasks own the same path and no production path is lead-owned.
`workstreams[*].dependsOn` is the only canonical dependency DAG; worker entries
declare ownership/review ceilings only and must never duplicate dependencies.

## Dependency DAG

```text
WS-01 neutrality
  -> WS-02 contracts
       -> WS-03 planning -----+
       -> WS-04 compiler -----+-> WS-07 CLI
       -> WS-05 workflow -----+      |       +-> WS-10 Codex ----+
       -> WS-06 audit --------+      +-> WS-08 skills -----------+
                                      -> WS-09 conformance ------+-> WS-14 release -> WS-15 final audit
                                                     +-> WS-11 Claude ---+
                                                     +-> WS-12 Cursor ---+
                                                     +-> WS-13 OpenCode -+
```

## Launch Waves

1. WS-01 alone; its current-tree neutrality report must be accepted.
2. WS-02 after WS-01.
3. WS-03, WS-04, WS-05 and WS-06 in parallel after WS-02.
4. WS-07 after all four engine services.
5. WS-08 and WS-09 in parallel after WS-07.
6. WS-10, WS-11, WS-12 and WS-13 run offline in parallel after WS-08 and
   WS-09. Live surface availability is not a launch gate.
7. WS-14 after all skills, conformance and adapter work.
8. WS-15 after WS-14 and every required task is independently accepted.

## Review Routing

- Every worker returns result v2; a distinct actor/run returns task review v2.
- Implementation, test or evidence defects return `REWORK` within the frozen
  task boundary after remediation approval. `ACCEPTED` requires no unresolved
  Medium, High or Blocker finding.
- Scope, architecture, public contract, ownership, DAG or acceptance changes
  return `CONTRACT_CHANGE`, stop dependents and require `REOPENED` plus
  refreeze.
- A missing live host capability caps adapter maturity; it never becomes a
  fabricated verification receipt.
- WS-15 never modifies product files. Its findings route through the same
  remediation versus refreeze decision.
- Before every launch and after every attempt, the controller verifies a fresh
  neutrality-v3 receipt under its lead-owned workflow namespace. Each operation
  uses a unique absent output path and a detached receipt published last; no
  worker receives external authority contents or signing material.
- WS-14 alone owns matrix aggregation, both clean builds, candidate payload
  identity, atomic final generation, release neutrality and read-only release
  verification; their explicit data dependency orders them without another
  workstream.
- After WS-15 acceptance, the controller enters `AWAITING_FINAL_PROOF`, runs
  finalization neutrality and writes only the exact lead-owned fixed-operation
  proof, idempotent WAL append and CAS state replacement. This is not an
  executable workstream write set and cannot be followed by another
  post-proof neutrality gate.
