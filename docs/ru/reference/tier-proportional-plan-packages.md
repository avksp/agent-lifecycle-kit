# Пакеты планов соразмерно уровню задачи

Release 2.23 добавляет компактный авторский формат для явно заданных задач S0/S1
с низким риском. Результат — canonical DRAFT из фактов автора. Ревью, freeze,
разрешение выполнения и доказательство завершения остаются отдельными этапами.
Существующий полный маршрут S2 сохраняется.

| Tier | Пригодность | Подготовка и ревью |
| --- | --- | --- |
| S0 | Одно явное механическое изменение, один исполнитель, все risk flags false | Компактный источник; отдельное ограниченное независимое ревью |
| S1 | До 12 последовательных изменений, один исполнитель, все risk flags false | Компактный источник; отдельное стандартное независимое ревью |
| S2 | Повышенный риск, внешние требования, несколько исполнителей или неопределённость | Существующий полный пакет и полное независимое ревью; компактный ввод отклоняется |

Отсутствующие tier или обязательные факты вызывают отказ, а не выбор S0/S1.
Флаги архитектуры, безопасности, производительности, браузера, внешней среды,
данных, релиза или внешней спецификации требуют S2. Для механического изменения
можно явно выбрать более высокий S1. ALK не придумывает ревьюера или бюджет.

## Команды подготовки

```bash
agent-lifecycle plan package-profiles
agent-lifecycle plan compact-explain --input tasks/compact-example/compact-input.json
agent-lifecycle plan compact-compile \
  --input tasks/compact-example/compact-input.json \
  --out tasks/compact-example/plan.manifest.json
```

Если репозиторий не является текущей папкой, укажите `--repository-root`.
Profiles и explain ничего не записывают. Диагностика explain может вернуть
`status: FAIL`; это не допуск. Компиляция создаёт только новый canonical-манифест
и отказывает при существующем выводе. Она не запускает модель, ревью, задачу или
workflow. Поле `planReview.verdict: READY_TO_FREEZE` в DRAFT означает обязательное
будущее условие, а не результат выполненного ревью.

Ниже CONTROLLED-пример, а не принятая производственная задача. Сохраните его
по указанному пути ввода. Замените автора, точную базовую ревизию, пути, команды,
риски и конечные лимиты на факты своего проекта.

```json
{
  "schemaVersion": "agent-compact-plan.v1",
  "tier": "S0",
  "mechanical": true,
  "package": {
    "id": "compact-example",
    "title": "Controlled compact authoring example",
    "planArtifactRoot": "tasks/compact-example",
    "artifactRoot": "work/compact-example"
  },
  "author": "fixture-author",
  "baseRevision": {
    "ref": "fixture-source",
    "sha": "1111111111111111111111111111111111111111"
  },
  "owner": "fixture-worker",
  "riskFlags": {
    "architecture": false,
    "security": false,
    "performance": false,
    "browser": false,
    "externalEnvironment": false,
    "data": false,
    "release": false,
    "externalSpecification": false
  },
  "changes": [
    {
      "id": "Import",
      "title": "Repair one missing import",
      "requirement": "Use the standard library module referenced by the worker.",
      "acceptance": "The bounded worker invocation no longer raises a missing-name error.",
      "evidenceDescription": "Controlled regression result, not a production run.",
      "evidencePath": "work/compact-example/import-result.json",
      "writes": [
        "src/example_worker.py"
      ],
      "validationCommands": [
        "python -m unittest tests.test_example_worker -q"
      ]
    }
  ],
  "orchestration": {
    "startMode": "manual-after-freeze",
    "remediationMode": "bounded-auto",
    "maxPlanReviewRounds": 4,
    "maxTaskAttempts": 3,
    "maxParallelTasks": 1,
    "maxValidationRunsPerTask": 4,
    "maxToolCallsPerIteration": 8,
    "maxUsageIterationsPerAttempt": 4,
    "maxToolCallsPerTask": 24,
    "maxToolCallsPerRun": 48,
    "maxReportedTokensPerTask": 4000,
    "maxReportedTokensPerRun": 8000,
    "maxEvidenceArtifactBytes": 65536,
    "maxEvidenceBytesPerTask": 131072,
    "maxEvidenceBytesPerRun": 262144,
    "maxTaskWallSeconds": 600,
    "maxRunWallSeconds": 1200,
    "maxContextBytes": 16384,
    "maxRenderedPacketBytes": 32768
  },
  "releaseImpact": "No publication, migration or release behaviour change.",
  "readOnly": [
    "src/existing_input.py"
  ],
  "forbiddenWrites": [
    ".git",
    ".alk",
    ".claude"
  ],
  "securityGates": [
    "No input, protected path or authority may be overwritten."
  ],
  "contextLimits": {
    "targetReviewerPacketTokens": 4000,
    "maxReviewerPacketTokens": 8000,
    "smallContextProfilesRequired": true
  }
}
```

Вход — закрытый UTF-8 JSON до 65 536 байт; canonical-вывод — до 262 144 байт.
Дублирующиеся и неизвестные ключи, нечисловые бесконечные значения, опасные пути,
неоднозначные имена и hard links вызывают отказ. Источник, манифест и ревью не
должны пересекаться. Источник находится внутри `package.planArtifactRoot`,
вывод — в его `plan.manifest.json`. Пути и полномочия проверяются относительно
выбранного репозитория. Проверки стабильности источника и очистка с привязкой
к identity созданного файла сохраняют существующий или чужой вывод.
Это локальные наблюдаемые проверки и координация соблюдающих lock писателей,
а не аттестованная непрерывная защита файлов или бюджет всего хоста.

## Дополните DRAFT перед freeze

Первоначальный inventory содержит компактный источник, canonical-манифест и
ожидаемый отчёт независимого ревью. **Перед `freeze-prepare` явно подготовьте
`acceptance-criteria.md` и добавьте его относительный путь в `planFiles` DRAFT.**
Штатный freeze требует этот checklist; компилятор не создаёт его скрытно.
Для примера таблица выглядит так:

```markdown
| ID | Requirement | Evidence | Criterion |
| --- | --- | --- | --- |
| `AC-Import` | `R-Import` | `EV-Import` | The bounded worker invocation no longer raises a missing-name error. |
```

Добавляемый путь — `tasks/compact-example/acceptance-criteria.md`. Сохраните
остальные записи inventory, связи AC/requirement/evidence и факты автора.
Это обычное редактирование ещё не проверенного DRAFT; менять так замороженный
или принятый план нельзя. Исходный пакет из трёх файлов штатно не проходит
freeze preparation без checklist.

Далее используйте существующий порядок:

1. Выполните `plan freeze-prepare` с явной новой папкой кандидата.
2. Получите настоящее независимое ревью точного кандидата и всех объявленных
   входов. Ревьюер должен действительно отличаться от автора и исполнителя.
3. Выполните `plan lock-create` с текущим принимающим отчётом и проверьте lock.
4. Скомпилируйте пакеты исполнителей; выполните обычные initialization, adoption
   и отдельное разрешение выполнения workflow.
5. Сохраните ревью задач, финальный аудит, учёт и применимые релизные gates.

Старый потребитель review v1 проверяет объявленный флаг `independent: true`;
он не устанавливает личность ревьюера и не доказывает независимость на уровне
хоста. Флаг не заменяет настоящего отдельного ревьюера. Компактная подготовка
не добавляет более сильной гарантии происхождения или автоматического одобрения.

## Отображение и доказательства

Изменение X получает R-X, AC-X, EV-X и WS-X. Явные требования, критерии, путь и
описание evidence, literal writes, последовательные зависимости и все лимиты
сохраняются. Команды каждого изменения находятся в
`workstreams[].plannedItems[].validationCommands`; глобальный inventory команд —
их объединение с сохранением первого вхождения. Команды записываются, а не исполняются.

Компактный v1 описывает обычные evidence. Словарь только с командами не попадает
в зарезервированное поле `acceptance.evidence[].validation`. Для типизированных
гарантий producer/subject или provenance нужен полный S2; неизвестные поля
гарантий вызывают отказ и не отбрасываются. Старые typed validators не меняются.

## Контролируемое сравнение и границы

Две явно подготовленные пары compact/verbose сохраняют все canonical-факты,
кроме перечисленных путей исходных документов. Общий checklist и дополнение
inventory учитываются с обеих сторон. Это структурные наблюдения CONTROLLED,
а не реальные сессии 2.21 или представительный производственный процесс.

| Пример | Verbose + checklist | Compact + checklist | Файлов с каждой стороны |
| --- | ---: | ---: | ---: |
| Controlled S0 | 5 308 байт | 2 539 байт | 2 |
| Controlled S1 | 6 931 байт | 3 190 байт | 2 |

Размер полученного canonical-вывода равен внутри каждой пары. Вход ревью измерен
отдельно. В трёх чередующихся локальных повторах компактная компиляция требовала
несколько больше локальной работы, чем одна валидация canonical-ввода;
доли миллисекунды не доказывают ускорение всего процесса. Запись вывода проверена
отдельно; неизменившиеся границы компиляции сохраняют привязку к исходным байтам.

Реальные трудозатраты автора, model input/output/cache tokens, активное время
модели, USD и экономия полного цикла — `UNAVAILABLE`, а не ноль. Разница в байтах
не доказывает экономию модели. Принятие опасного ввода, потеря фактов, ослабление
гарантий или регрессия S2 блокируют выпуск. Отсутствие реальной экономики само
по себе не выключает функцию; проверки качества и полномочий обязательны.

См. [полноту плана](plan-completeness.md), [CLI](cli.md),
[границы полномочий](authority-artifact-boundaries.md) и
[продолжение workflow](workflow-continuation.md).
