# Учёт ресурсов релиза

Учёт релиза преобразует явно указанные локальные подтверждения в один
детерминированный и проверенный артефакт `agent-release-accounting.v1`. Это
граница наблюдаемости, а не биллинг и не полномочия workflow. Команда не
запускает модель, процесс хоста или сеть и не подставляет значения вместо
недоступной телеметрии.

## Измерение фаз

Подготовьте объект `agent-phase-resource-input.v1`:

```json
{
  "schemaVersion": "agent-phase-resource-input.v1",
  "phases": [
    {
      "phaseId": "implementation",
      "phaseKind": "IMPLEMENTATION",
      "taskId": "WS-01",
      "operationId": "ws-01-result",
      "tokens": {"input": 700, "output": 300, "total": 1000},
      "steps": 7,
      "resources": {"toolCalls": 12, "validationRuns": 3},
      "durationMs": 420000,
      "receiptDigests": []
    }
  ],
  "lineage": {"runId": "release-run-1", "sourceRevision": "abc123"},
  "sourceArtifacts": []
}
```

Создайте каноническое измерение:

Результат использует схему `agent-phase-resource-measurement.v1`.

```bash
agent-lifecycle metrics phase-resources \
  --input work/phase-resource-input.json \
  --out work/phase-resources.json
```

Размер входа ограничен 1 МиБ, число фаз - 256. Выходной файл создаётся без
замены. Токены, шаги, длительность и счётчики ресурсов должны быть
неотрицательными целыми; денежные и неизвестные поля ресурсов отклоняются.

## Сборка учёта релиза

Команда принимает одно или несколько измерений фаз либо артефактов
`agent-release-accounting-source.v1` внутри `--project-root`:

```bash
agent-lifecycle metrics release-accounting \
  --release-id 2.6.0 \
  --project-root . \
  --artifact work/phase-resources.json \
  --artifact work/external-audit-accounting.json \
  --provenance work/release-provenance.json \
  --out work/release-accounting.json
```

Допускается не более 64 уникальных исходных артефактов и 1024 итоговых
записей. Каждый файл читается устойчиво в границах репозитория с лимитом 1 МиБ.
Выход за корень, симлинки, повтор байтов и повтор канонического содержимого
завершаются безопасным отказом. Канонический результат проверяется до выдачи
квитанции и не заменяет существующий файл.

## Представления и метрики

В результате всегда четыре представления:

- `alkProcess`: планирование и координация жизненного цикла;
- `implementation`: реализация продукта;
- `audit`: независимая и продуктовая проверка;
- `postAuditRemediation`: исправления по итогам аудита.

Для каждого отдельно считаются `tokens`, `steps`, `elapsedWallMs` и
`computeMs`. `elapsedWallMs` - прошедшее время; `computeMs` может суммировать
параллельные вычисления аудиторов и не складывается с wall time. Отсутствующая
телеметрия представляется как `{"status":"UNAVAILABLE","value":null}`, а не
нулём. Неполные и смешанные данные сохраняют статусы `PARTIAL` и `MIXED`.

В итоги входят только записи с `additive: true`. Снимок длинной цели по
нескольким релизам должен быть неаддитивным и остаётся видимым в `exclusions`
с причиной `NON_ADDITIVE_SCOPE`. Потребитель обязан учитывать статус метрики и
исключения, а не только число.

## Происхождение данных

Необязательный файл provenance независимо объявляет:

- `controllerVersion` и `coreVersion`;
- `hostPluginVersion` и `skillPackageVersion`;
- `runAlkVersion`, `runId` и `sourceRevision`;
- `measurementDigest`.

Наблюдаемые и объявленные значения не смешиваются. Расхождение получает
`MISMATCH`, не доказывает свежесть и никогда не превращается в `ATTESTED`.
Исходные дескрипторы, статусы идентичности, итоги и исключения входят в
`accountingDigest`.

## Существующий отчёт затрат

`metrics cost-report` принимает измерение фаз и использует объявленные токены
и шаги вместо оценки по размеру JSON:

```bash
agent-lifecycle metrics cost-report \
  --artifact work/phase-resources.json \
  --project-root . \
  --mode release \
  --out work/cost-report.json
```

Учёт релиза является рекомендательным evidence. Он не принимает задачу, не
авторизует выполнение, не снижает quality gate и не заявляет production
promotion.
