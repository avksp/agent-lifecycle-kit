# Запуск набора эталонных задач

Используйте встроенный набор, когда нужно повторяемо сравнить изменения в
процессе ALK. Учётная запись модели и внешний инструмент не требуются.

Для сравнения нескольких запусков адаптеров и сред перейдите к разделу
[проверка вариантов выполнения по эталонным задачам](../reference/benchmark-qualification.md).
Это руководство описывает правило одной задачи, а отдельная проверка добавляет
стратифицированную выборку и минимальные требования к подтверждениям.

## 1. Возьмите пример

```bash
mkdir -p work/benchmark
cp tests/benchmarks/fixtures/accepted-pass.json work/benchmark/submission.json
```

Пример описывает успешный результат планирования. Замените объекты `evidence`
артефактами своего контролируемого запуска, сохранив соответствие `taskId` и
`taskVersion` манифесту набора.

## 2. Выполните оценку

```bash
agent-lifecycle benchmark evaluate \
  --suite benchmarks/reference-tasks/manifest.json \
  --artifact work/benchmark/submission.json \
  --out work/benchmark/evaluation.json
```

Сначала проверьте поля:

- `status`: прошёл ли принятый результат детерминированное правило;
- `summary.falseAcceptanceCount`: был ли принят результат, отклонённый правилом;
- `measurements.tokens.byConfidence`: подтверждённые и оценочные токены;
- `measurements.measurementGaps`: какие измерения не были переданы.

## 3. Проверьте отрицательный пример

```bash
agent-lifecycle benchmark evaluate \
  --suite benchmarks/reference-tasks/manifest.json \
  --artifact tests/benchmarks/fixtures/accepted-false.json \
  --out work/benchmark/false-acceptance.json

python -c 'import json; value=json.load(open("work/benchmark/false-acceptance.json")); assert value["status"] == "FAIL" and value["summary"]["falseAcceptanceCount"] == 1'
```

Команда оценки завершается штатно, потому что создала корректный отрицательный
артефакт. Вторая команда делает результат обязательным условием автоматизации.

## Для опытных пользователей

Можно подготовить отдельный вход для каждой задачи из
`benchmarks/reference-tasks/manifest.json`, сохранить полученные артефакты и
сравнить качество, время, повторы и токены с обозначенным уровнем уверенности.
Не сравнивайте `ESTIMATED` и `ATTESTED` как данные одинакового происхождения.

Формат входа, правила и границы безопасности приведены в
[справочнике по оценке](../reference/reference-task-evaluation.md).
