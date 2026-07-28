# Release artifacts

This directory is reserved for generated release-candidate inventories and
content-addressed generations.

Generated files are evidence, not source of truth. Recreate the offline
inventory and evidence with:

```bash
EVIDENCE_DIR=release/candidate/evidence
mkdir -p "$EVIDENCE_DIR" release/candidate
PYTHONPATH=src python tools/release/assemble_release_candidate.py --manifest plans/standalone-v1/plan.manifest.json --inventory release/candidate/inventory.json --evidence "$EVIDENCE_DIR"/release-assembly.json
PYTHONPATH=src python tools/release/verify_release_candidate.py --inventory release/candidate/inventory.json --evidence "$EVIDENCE_DIR"/release-verification.json
```

`plans/standalone-v1` is historical release evidence. Final-candidate
verification over that package is expected to reject the current revision
14/16 lineage mismatch unless the package is explicitly refreshed and locked.
