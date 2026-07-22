# Release architecture

The release architecture has two stages:

1. Offline release candidate.
2. Production promotion.

The offline candidate is local and reproducible. It assembles a
content-addressed inventory from the source tree, documentation, shared skills,
adapters, conformance data, tests and governance files. It validates support
matrix and deferred-promotion contracts without claiming external execution.

Production promotion is intentionally separate. It requires signed external
receipts for platform matrix execution, release neutrality and live cost
calibration. Missing external authority blocks promotion and must not be
converted into a local PASS claim.
