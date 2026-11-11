# Проверка исходного дерева перед выпуском

Запускайте проверки из чистого checkout. Инвентарь и доказательства создаются в
игнорируемом каталоге `release/candidate/`: это одноразовые генерируемые файлы,
а не источник правды. История релизов хранится в `CHANGELOG.md` и опубликованных
GitHub Releases.

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

Сборка и проверка должны проходить без сети. Генерируемые файлы не должны менять
`git status --short`; любой отслеживаемый путь `release/**` является ошибкой
гигиены репозитория. Планы и сырые доказательства остаются в игнорируемых
`tasks/`, `work/` или `.alk/`.

Успешная локальная проверка не заменяет промышленное продвижение, внешнюю
публикацию и подписанные подтверждения.

## Квалификация main и публикация

Native completion, полный PR CI и квалификация push в main имеют отдельные
доказательства. Итоговый отчёт main фиксирует проверенные исходники, режим
и попытку CI, свежие проверки интеграции и упаковки. Сборка main создаёт один
wheel и один sdist. Smoke-проверка использует эти же файлы и отчёт сборки.
CodeQL публикует отдельный результат для того же коммита.

При публикации GitHub Release проверка с доступом на чтение разрешает тег и
подтверждает успешную квалификацию push в main и CodeQL для этого SHA.
Задачи PyPI и Agent Plugins делают checkout проверенного коммита и повторно
проверяют тег и происхождение от main перед сборкой и перед загрузкой.
Ручной замер служит только для сравнения. Для опубликованных wheel, sdist
и архива плагина по-прежнему требуется проверка доставки, а для официального
wheel также нужны результаты тестов в чистой установке.
