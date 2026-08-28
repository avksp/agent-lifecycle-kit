# Release artifacts

This directory is reserved for generated release-candidate inventories and
content-addressed generations.

Generated files are evidence, not source of truth. Recreate the offline
inventory and evidence with:

```bash
EVIDENCE_DIR=release/candidate/evidence
mkdir -p "$EVIDENCE_DIR" release/candidate
PYTHONPATH=src python tools/release/assemble_release_candidate.py --manifest profiles/release/source-release-profile.v1.json --inventory release/candidate/inventory.json --evidence "$EVIDENCE_DIR"/release-assembly.json
PYTHONPATH=src python tools/release/verify_release_candidate.py --inventory release/candidate/inventory.json --evidence "$EVIDENCE_DIR"/release-verification.json
```

Lifecycle plans and final-candidate state remain local under ignored `work/`,
`tasks/` or `.alk/` paths. They are not source-release inputs and must not be
added to Git.
