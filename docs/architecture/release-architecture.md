# Release architecture

The release architecture has two stages:

1. Offline release candidate.
2. Production promotion.

The offline candidate is local and reproducible. It assembles a
content-addressed inventory from the source tree, documentation, shared skills,
adapters, conformance data, tests and governance files. It validates support
matrix and deferred-promotion contracts without claiming external execution.

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
