# Offline source-release checks

Run the local offline source-release checks from the repository root. Use a
fresh temporary evidence directory for release-candidate artifacts; historical
`plans/standalone-v1` evidence must not be treated as current proof unless it
is explicitly refreshed and locked.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m agent_lifecycle plan check --manifest tasks/release-0-3/plan.manifest.json --lock tasks/release-0-3/plan.lock.json
PYTHONPATH=src python tests/contracts/run_digest_authority_check.py --evidence tasks/release-0-3/evidence/digest-authority-tests.json
PYTHONPATH=src python tools/release/verify_negative_suite_coverage.py --catalog tasks/release-0-3/05-validation-and-evidence.md --tests-root tests --expected-range NEG-R03-01..NEG-R03-20 --evidence tasks/release-0-3/evidence/negative-suite-coverage.json
PYTHONPATH=src python tools/release/verify_task_packet_context.py --manifest tasks/release-0-3/plan.manifest.json --profile profiles/small-context-profile.v1.json --summary tests/release/fixtures/release-0-3/context-summary.json --out-dir tasks/release-0-3/workflow/task-packets --target-windows 4k-strict,8k --evidence tasks/release-0-3/evidence/context-fit.json

EVIDENCE_DIR=tasks/release-0-3/evidence/release-candidate
CANDIDATE_DIR=tasks/release-0-3/evidence/release-candidate
RELEASE_NEUTRALITY_REPORT=tasks/release-0-3/evidence/release-candidate/release-neutrality-report.json
rm -rf "$EVIDENCE_DIR" "$CANDIDATE_DIR"
mkdir -p "$EVIDENCE_DIR" "$CANDIDATE_DIR" "$(dirname "$RELEASE_NEUTRALITY_REPORT")"
PYTHONPATH=src python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json --evidence "$EVIDENCE_DIR"/support-matrix-contract.json
PYTHONPATH=src python tools/release/validate_deferred_promotion.py --profile plans/standalone-v1/.agent-plan/standalone-v1/benchmark-authority-profile.v1.json --evidence "$EVIDENCE_DIR"/deferred-promotion-contract.json
PYTHONPATH=src python tools/release/assemble_release_candidate.py --manifest plans/standalone-v1/plan.manifest.json --inventory "$CANDIDATE_DIR"/inventory.json --evidence "$EVIDENCE_DIR"/release-assembly.json
PYTHONPATH=src python tools/release/verify_release_candidate.py --inventory "$CANDIDATE_DIR"/inventory.json --evidence "$EVIDENCE_DIR"/release-verification.json
python -c "from pathlib import Path; Path('$RELEASE_NEUTRALITY_REPORT').unlink(missing_ok=True)"
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --report "$RELEASE_NEUTRALITY_REPORT" --require-zero-findings
PYTHONPATH=src python tests/package/run_packaging_smoke.py --dist-dir /tmp/agent-lifecycle-r03-dist --evidence tasks/release-0-3/evidence/packaging-smoke.json
```

The current `plans/standalone-v1` directory is historical release evidence. It
intentionally preserves a revision 16 manifest with revision 14 workflow and
finalization artifacts, so final-candidate verification against it must fail
closed with a lineage blocker:

```bash
set +e
PYTHONPATH=src python tools/release/verify_final_candidate.py --manifest plans/standalone-v1/plan.manifest.json --state plans/standalone-v1/workflow/run.state.json --release-evidence-dir "$EVIDENCE_DIR" --output "$EVIDENCE_DIR"/final-candidate-audit.json
rc=$?
set -e
test "$rc" -ne 0
python - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("tasks/release-0-3/evidence/release-candidate/final-candidate-audit.json").read_text(encoding="utf-8"))
codes = {item.get("code") for item in payload.get("blockers", [])}
assert payload.get("status") == "FAIL", payload
assert "lineage-check-failed" in codes, payload
PY
```

A passing final-candidate proof requires a fresh current run package or an
explicitly refreshed and locked standalone package. That proof is still only an
offline source-release proof; do not label it production-ready until the
production-promotion contract has external signed receipts.
