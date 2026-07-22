# WS-05 Workflow Context Projection

This file is a compact execution projection. The frozen task packet remains
authoritative for requirement text, acceptance ids, evidence ids, ownership and
writes. The locked budget, neutrality and final-proof profiles remain
authoritative for numeric and cryptographic details.

## Required runtime seams

- Persist state with expected-revision CAS and an append-only, fsynced WAL.
- Allocate one validation operation id per run/task/attempt/phase transaction;
  require every operation-scoped command in the submitted result to carry the
  identical closed binding and render only frozen command/path templates.
- Enforce authorization, dependency waves, task deadlines, run deadline,
  cancellation, bounded attempts, resource ledgers and independent reviews.
- Execute controller neutrality before launch and after each attempt. Bind each
  receipt to the exact run, package, task, attempt, phase, operation, plan and
  source revision. Never expose authority rules or signing keys to workers.
- Before WS-14 dispatch, execute the ordered gate chain
  `neutrality-current-tree -> release-authority-preflight ->
  release-launch-neutrality`. The middle gate verifies and durably binds the
  CI allowlist, benchmark baseline and live-calibration profile; the final gate
  scans that new receipt and must be the last mutating pre-launch gate.
- Route logical model calls by capability and role, preserve actor/reviewer
  independence, account cumulative usage across fallback and remediation, and
  fail closed when attested usage is missing.

## Terminal protocol

The terminal audit result is `READY_FOR_FINALIZATION`, not `COMPLETE`. After
its post-attempt gate and independent accepted review, atomically enter
`AWAITING_FINAL_PROOF` with expected state revision/digest, WAL prefix identity
and a newly allocated finalization operation id.

Finalization neutrality treats the accepted review, all predecessor artifacts,
future proof path, current state and WAL as scan inputs. Its operation outputs
are only its primary artifact and detached receipt. A separate canonical
controller output-set digest binds: create-no-replace proof publication,
idempotent predecessor-bound WAL append and expected-revision state CAS. Only
that transaction reaches `COMPLETE`. Identical replay returns existing durable
identities; partial, conflicting or drifted replay blocks the run.

## Evidence focus

Positive and negative tests cover dependency scheduling, authorization,
operation-binding substitution, controller gate failure, usage overrun,
timeouts, cancellation, crash points before and after each terminal write,
idempotent replay and plan/source/profile/review/gate/inventory/change-set drift.
