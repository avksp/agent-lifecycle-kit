# Offline source-release checks

Run the offline checks from a clean checkout. The release workflow generates
the candidate inventory and evidence under ignored `release/candidate/`; these
files are disposable outputs, not source of truth. `CHANGELOG.md` and published
GitHub Releases carry release history.

```bash
EVIDENCE_DIR=release/candidate/evidence
CANDIDATE_DIR=release/candidate
rm -rf "$CANDIDATE_DIR"
mkdir -p "$EVIDENCE_DIR"

PYTHONPATH=src python tools/release/assemble_release_candidate.py \
  --manifest profiles/release/source-release-profile.v1.json \
  --inventory "$CANDIDATE_DIR/inventory.json" \
  --evidence "$EVIDENCE_DIR/release-assembly.json"
PYTHONPATH=src python tools/release/verify_release_candidate.py \
  --inventory "$CANDIDATE_DIR/inventory.json" \
  --evidence "$EVIDENCE_DIR/release-verification.json"
PYTHONPATH=src python -m agent_lifecycle.neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --report "$EVIDENCE_DIR/release-neutrality-report.json" \
  --require-zero-findings

test -z "$(git ls-files release)"
git status --short
```

Assembly and verification must pass without network access. Generated output
must not alter `git status --short`; a tracked `release/**` path is a repository
hygiene failure. Lifecycle plans and raw receipts remain local under ignored
`tasks/`, `work/` or `.alk/` roots.

A passing offline candidate does not claim production promotion. External
publication, live-host and signed evidence requirements remain separate.
