# Release artifacts

This directory is reserved for generated release-candidate inventories and
content-addressed generations.

Generated files are evidence, not source of truth. Recreate them with:

```bash
PYTHONPATH=src python tools/release/assemble_release_candidate.py --manifest plans/standalone-v1/plan.manifest.json --inventory release/candidate/inventory.json --evidence plans/standalone-v1/evidence/ws-14/release-assembly.json
```
