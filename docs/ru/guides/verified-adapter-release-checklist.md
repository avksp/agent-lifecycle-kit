# Чек-лист выпуска проверенного адаптера

Применяйте чек-лист после новых или изменённых `VERIFIED` evidence host adapter. Tag, GitHub Release, CI, docs, version metadata и evidence claims проверяются отдельно.

## Локальная готовность

1. Проверьте working tree и текущую branch:

```bash
git status --short --branch
git log --oneline --decorate -5
```

2. Обновите package version, plugin manifests, marketplace refs, changelog, release notes, README files, adapter docs, support matrix и release validators для patch или minor version.
3. Выполните локальные проверки:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
python tools/release/validate_adapter_conformance.py --baseline conformance/core/adapter-baseline.v1.json --evidence <adapter-conformance-evidence.json>
python tools/release/validate_docs_compat.py --evidence <docs-compat-evidence.json>
python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile profiles/release/ci-matrix-profile.v2.json --evidence <support-matrix-evidence.json>
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --report <neutrality-report.json> --require-zero-findings
PYTHONPATH=src python tests/package/run_packaging_smoke.py --dist-dir <dist-dir> --evidence <packaging-smoke-evidence.json>
```

4. Пересоберите и проверьте offline candidate inventory:

```bash
PYTHONPATH=src python tools/release/assemble_release_candidate.py --manifest profiles/release/source-release-profile.v1.json --inventory release/candidate/inventory.json --evidence <release-assembly-evidence.json>
PYTHONPATH=src python tools/release/verify_release_candidate.py --inventory release/candidate/inventory.json --evidence <release-verification-evidence.json>
```

5. До commit проверьте staged diff:

```bash
git diff --check
git diff --cached | rg -n "(/(Volumes|Users|private|var/folders)/|to[k]en=|se[c]ret)" || true
```

Staged scan обязательно проверяется вручную. Generated local evidence может содержать machine-local paths; оно должно оставаться ignored, если redacted summary не включается в commit намеренно.

## Публикация

1. Создайте и отправьте commit.
2. Создайте локальный annotated tag.
3. Отправьте branch и tag.
4. Проверьте remote tag отдельно от local tag:

```bash
git ls-remote --tags origin '<tag>*'
```

5. Создайте GitHub Release object из committed release notes.
6. Проверьте GitHub Release object отдельно от tag:

```bash
gh release view <tag> --json tagName,isDraft,isPrerelease,url,name,publishedAt
```

7. Проверьте CI status release commit:

```bash
gh run list --branch main --limit 8 --json databaseId,headSha,name,status,conclusion,url
```

## Артефакты исходного выпуска

Binary assets намеренно не включаются в source release, если packaging smoke доказывает сборку wheel из tag, а release notes явно не заявляют binary publication. Прикреплять binaries можно только когда release plan явно включает signed artifact publication и verification.
