# Offline source-release checks

Run the local offline source-release checks from the repository root. Use a
fresh temporary evidence directory for release-candidate artifacts. Lifecycle
plans and state remain local under ignored `work/`, `tasks/` or `.alk/` paths.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m agent_lifecycle plan check --manifest work/release-0-3/plan.manifest.json --lock work/release-0-3/plan.lock.json
PYTHONPATH=src python tests/contracts/run_digest_authority_check.py --evidence work/release-0-3/evidence/digest-authority-tests.json
PYTHONPATH=src python tools/release/verify_negative_suite_coverage.py --catalog work/release-0-3/05-validation-and-evidence.md --tests-root tests --expected-range NEG-R03-01..NEG-R03-20 --evidence work/release-0-3/evidence/negative-suite-coverage.json
PYTHONPATH=src python tools/release/verify_task_packet_context.py --manifest work/release-0-3/plan.manifest.json --profile profiles/small-context-profile.v1.json --summary tests/release/fixtures/release-0-3/context-summary.json --out-dir work/release-0-3/workflow/task-packets --target-windows 4k-strict,8k --evidence work/release-0-3/evidence/context-fit.json

EVIDENCE_DIR=work/release-0-3/evidence/release-candidate
CANDIDATE_DIR=work/release-0-3/evidence/release-candidate
RELEASE_NEUTRALITY_REPORT=work/release-0-3/evidence/release-candidate/release-neutrality-report.json
rm -rf "$EVIDENCE_DIR" "$CANDIDATE_DIR"
mkdir -p "$EVIDENCE_DIR" "$CANDIDATE_DIR" "$(dirname "$RELEASE_NEUTRALITY_REPORT")"
PYTHONPATH=src python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile profiles/release/ci-matrix-profile.v2.json --evidence "$EVIDENCE_DIR"/support-matrix-contract.json
PYTHONPATH=src python tools/release/validate_deferred_promotion.py --profile profiles/release/benchmark-authority-profile.v1.json --evidence "$EVIDENCE_DIR"/deferred-promotion-contract.json
PYTHONPATH=src python tools/release/assemble_release_candidate.py --manifest profiles/release/source-release-profile.v1.json --inventory "$CANDIDATE_DIR"/inventory.json --evidence "$EVIDENCE_DIR"/release-assembly.json
PYTHONPATH=src python tools/release/verify_release_candidate.py --inventory "$CANDIDATE_DIR"/inventory.json --evidence "$EVIDENCE_DIR"/release-verification.json
python -c "from pathlib import Path; Path('$RELEASE_NEUTRALITY_REPORT').unlink(missing_ok=True)"
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope tracked-release --policy policy/neutrality.policy.json --report "$RELEASE_NEUTRALITY_REPORT" --require-zero-findings
PYTHONPATH=src python tests/package/run_packaging_smoke.py --dist-dir /tmp/agent-lifecycle-r03-dist --evidence work/release-0-3/evidence/packaging-smoke.json
```

A passing final-candidate proof requires a fresh current run package or an
explicitly refreshed and locked local package. That proof is still only an
offline source-release proof; do not label it production-ready until the
production-promotion contract has external signed receipts.

`tracked-release` scans only staged Git identities and their current working
tree content. A dedicated evidence job may add `--include-local-artifacts`, but
only the repository-relative roots in `localArtifactRoots` are eligible. See
[Neutrality scanning](../reference/neutrality.md).
