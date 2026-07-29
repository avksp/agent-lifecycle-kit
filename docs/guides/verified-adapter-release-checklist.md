# Verified-adapter release checklist

Use this checklist after a host adapter has new or changed `VERIFIED` evidence.
It keeps tag, GitHub Release, CI, docs, version metadata, and evidence claims
separate.

## Local Readiness

1. Confirm the working tree and current branch:

```bash
git status --short --branch
git log --oneline --decorate -5
```

2. Update package version, plugin manifests, marketplace refs, changelog,
   release notes, README files, adapter docs, support matrix, and release
   validators for the patch or minor version.

3. Run local checks:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
python tools/release/validate_docs_compat.py --evidence <docs-compat-evidence.json>
python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json --evidence <support-matrix-evidence.json>
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --report <neutrality-report.json> --require-zero-findings
PYTHONPATH=src python tests/package/run_packaging_smoke.py --dist-dir <dist-dir> --evidence <packaging-smoke-evidence.json>
```

4. Rebuild and verify the offline candidate inventory:

```bash
PYTHONPATH=src python tools/release/assemble_release_candidate.py --manifest plans/standalone-v1/plan.manifest.json --inventory release/candidate/inventory.json --evidence <release-assembly-evidence.json>
PYTHONPATH=src python tools/release/verify_release_candidate.py --inventory release/candidate/inventory.json --evidence <release-verification-evidence.json>
```

5. Scan the staged diff before commit:

```bash
git diff --check
git diff --cached | rg -n "(/(Volumes|Users|private|var/folders)/|to[k]en=|se[c]ret)" || true
```

The staged scan must be reviewed manually. Generated local evidence may include
machine-local paths; it must stay ignored unless a redacted summary is
intentionally committed.

## Publication

1. Create and push the commit.
2. Create a local annotated tag.
3. Push the branch and tag.
4. Verify the remote tag separately from the local tag:

```bash
git ls-remote --tags origin '<tag>*'
```

5. Create the GitHub Release object from the committed release notes.
6. Verify the GitHub Release object separately from the tag:

```bash
gh release view <tag> --json tagName,isDraft,isPrerelease,url,name,publishedAt
```

7. Verify CI status for the release commit:

```bash
gh run list --branch main --limit 8 --json databaseId,headSha,name,status,conclusion,url
```

## Source-release Assets

Binary assets are intentionally omitted for a source release when packaging
smoke proves the wheel can be built from the tag and the release notes state
that no binary publication is claimed. Attach binaries only when the release
plan explicitly includes signed artifact publication and verification.
