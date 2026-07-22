# WS-14 Release Context Projection

The frozen packet supplies exact requirement text, command order, evidence ids,
ownership and writes. Machine profiles supply exact platform, authority,
archive, budget and digest fields.

Before any external dispatch, the controller must complete the ordered
pre-launch chain `neutrality-current-tree -> release-authority-preflight ->
release-launch-neutrality`. The authority receipt binds the exact CI allowlist,
baseline and live-profile identities; the final neutrality receipt covers that
new controller artifact and is the launch authority stored in state.

## Ordered release transaction

1. Run all nine authenticated matrix legs from `ci-matrix-profile.v2.json`.
2. Aggregate the exact leg set and require one shared non-recursive
   `candidatePayloadInventoryDigest` plus its object-manifest digest.
3. Run cold/warm live calibration through the external provider-neutral
   authority without embedding provider or model names in core contracts.
4. Build twice in isolated clean environments; require candidate payload bytes
   to equal the matrix digest.
5. Assemble the complete release unit in same-filesystem staging, compute the
   separate final inventory digest, write the commit marker last, fsync and
   atomically rename without replacement to the content-addressed generation.
6. Run release neutrality against that committed generation and assembly
   receipt, then run the read-only `--no-build` verifier and prove pre/post
   Merkle equality.

The assembly and release-neutrality commands share the controller-allocated
run/task/attempt/phase validation transaction identity so the latter consumes
the exact former receipt through frozen rendered paths. Their output files are
distinct and create-no-replace. Partial staging, occupied generations,
candidate/final digest substitution, matrix mismatch, post-scan mutation or
authority drift blocks publication.
