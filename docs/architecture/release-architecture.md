# Release architecture

The release architecture has two stages:

1. Offline release candidate.
2. Production promotion.

The offline candidate is local and reproducible. It assembles a
content-addressed inventory from the source tree, documentation, shared skills,
adapters, conformance data, tests and governance files. It validates support
matrix and deferred-promotion contracts without claiming external execution.
It also validates the public contract policy so schema ids, CLI JSON envelopes
and stable error codes remain predictable for adapters and release scripts.

Production promotion is intentionally separate. It requires signed external
receipts for platform matrix execution, release neutrality, live host lifecycle
conformance and live cost calibration. Missing external authority blocks
promotion and must not be converted into a local PASS claim.

Live host conformance and live cost calibration are represented as profiles and
verifiers rather than local model benchmarks. The offline release ships the
contracts and validators; production promotion supplies signed live receipts.
The verifiers reject synthetic replay data, missing usage attestations,
host-operation envelope bypasses, incomplete scenario/cohort coverage and budget
overruns, including the dedicated 4k-strict compact-context scenario.

## Execution gates

Local execution gates run before any production-promotion claim:

- human acceptance checklists are validated against the frozen manifest;
- adapter progress is captured as neutral `agent-adapter-event.v1` streams;
- task acceptance rejects unowned, read-only or forbidden changed files;
- each attempt binds to its launch baseline and requires reconciliation on
  drift;
- optional multi-review quorum receipts are enforced only when a frozen plan
  opts in for that phase;
- finalization requires a completion signal or explicit evidence-bound waiver;
- an adopted `completionCheck` requires a matching completion-check receipt
  before final proof can be written;
- human-only actions pause the run until an external-action receipt is present.

These gates make local completion more honest, but they do not promote an
adapter to `VERIFIED`. Promotion still requires the separate live host
conformance and calibration receipts described above.

## Resource evidence

Lifecycle cost accounting is release evidence for resource discipline. A cost
report separates implementation, product validation, pipeline compliance and
coordination so a release can show that ALK is helping task delivery instead of
spending hidden effort on its own process.

Strict and release modes may run deeper checks, but over-limit pipeline cost
needs an explicit reason. The cost receipt does not replace tests, review,
support matrix validation or final proof.
