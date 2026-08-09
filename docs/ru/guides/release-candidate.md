# Проверка исходного дерева перед выпуском

Запускайте проверку из корня репозитория. Исторические материалы
`plans/standalone-v1` нельзя считать текущим подтверждением без явного
обновления и фиксации.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v

RELEASE_NEUTRALITY_REPORT=work/release/evidence/release-neutrality-report.json
python -c "from pathlib import Path; Path('$RELEASE_NEUTRALITY_REPORT').unlink(missing_ok=True)"
PYTHONPATH=src python -m agent_lifecycle.neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --report "$RELEASE_NEUTRALITY_REPORT" \
  --require-zero-findings

PYTHONPATH=src python tests/package/run_packaging_smoke.py \
  --dist-dir /tmp/agent-lifecycle-release-dist \
  --python python \
  --evidence work/release/evidence/packaging-smoke.json
```

Область `tracked-release` связывает отчёт с индексом Git и текущей ревизией.
Неотслеживаемые и игнорируемые файлы не читаются. Для отдельной проверки
локальных подтверждений можно добавить `--include-local-artifacts`, но команда
прочитает только относительные корни из `localArtifactRoots`. Обычный релизный
шаг не должен включать этот флаг.

Подробности: [проверка нейтральности](../reference/neutrality.md). Успешная
локальная проверка исходного дерева не заменяет внешние подписанные
подтверждения промышленного продвижения.
