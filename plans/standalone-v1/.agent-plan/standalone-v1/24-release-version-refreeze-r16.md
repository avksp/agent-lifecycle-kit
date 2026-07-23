# Release version ownership refreeze r16

Revision 16 closes the release-preparation ownership gap for the `v0.1.2`
source release candidate.

Problem:

- root publication manifests are release artifacts, but the frozen write-set did
  not assign `.codex-plugin`, `.claude-plugin`, `.cursor-plugin`, or
  `.agents/plugins` to a workstream;
- the cross-adapter publication manifest test is a release-governance check, but
  `tests/adapters/test_publication_manifests.py` was not assigned to release
  engineering;
- preparing a patch release requires updating these files together with
  package metadata, docs, adapter projections and release inventory.

Resolution:

- keep product scope, task DAG, adapter maturity, production-promotion boundary
  and runtime behavior unchanged;
- assign root publication manifests and the shared publication-manifest test to
  WS-14 as release engineering ownership;
- keep adapter-local projection files under their existing adapter workstreams;
- require fresh tests, neutrality, ownership, release assembly and release
  verification before tagging.

Execution impact:

- no new host capability or `VERIFIED` claim is introduced by this refreeze;
- release status remains source-release `EXPERIMENTAL`;
- `v0.1.2` may be tagged only after the release-preparation commit and green
  local/CI gates.
