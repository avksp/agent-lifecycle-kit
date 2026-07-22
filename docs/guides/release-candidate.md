# Offline source-release checks

Run the local offline source-release checks from the repository root:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json --evidence plans/standalone-v1/evidence/ws-14/support-matrix-contract.json
PYTHONPATH=src python tools/release/validate_deferred_promotion.py --profile plans/standalone-v1/.agent-plan/standalone-v1/benchmark-authority-profile.v1.json --evidence plans/standalone-v1/evidence/ws-14/deferred-promotion-contract.json
PYTHONPATH=src python tools/release/assemble_release_candidate.py --manifest plans/standalone-v1/plan.manifest.json --inventory release/candidate/inventory.json --evidence plans/standalone-v1/evidence/ws-14/release-assembly.json
PYTHONPATH=src python tools/release/verify_release_candidate.py --inventory release/candidate/inventory.json --evidence plans/standalone-v1/evidence/ws-14/release-verification.json
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --report plans/standalone-v1/evidence/ws-14/release-neutrality-report.json --require-zero-findings
```

The result is an offline source-release proof only. Do not label it
production-ready until the production-promotion contract has external signed
receipts.
