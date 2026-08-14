# Профиль рабочего процесса проекта

Профиль рабочего процесса проекта — это небольшой локальный файл с настройками
по умолчанию для единой команды запуска ALK. Он помогает использовать в проекте
одинаковые этапы, адаптер, уровень риска, режим проверки и ограничители ресурсов,
не помещая настройки проекта в план ALK.

Профиль принадлежит проекту, который его использует. Стандартный путь
`.alk/project-profile.json` исключён из Git и предназначен для локальной
работы. Файл может сохраняться между запусками, но его не следует коммитить
или считать источником истины проекта. Он не заменяет спецификацию,
зафиксированный план или lock-файл плана.

## Создание и проверка профиля

Создайте минимальный корректный профиль в текущем проекте:

```bash
agent-lifecycle project profile init --adapter <adapter-id> --out .alk/project-profile.json
```

Необязательный параметр `--adapter` записывает адаптер по умолчанию для `start`.
Если его не указывать, задайте `defaultAdapter` в локальном файле или передавайте
`--adapter` в каждой команде. После изменения локального файла проверьте
разрешённые настройки:

```bash
agent-lifecycle project profile check
agent-lifecycle project profile check --adapter <adapter-id> --risk S1
```

Для зафиксированного плана передайте манифест плана и его lock-файл:

```bash
agent-lifecycle project profile check \
  --manifest path/to/plan.manifest.json \
  --lock path/to/plan.lock.json \
  --out .alk/effective-project-profile.json
```

Команда создаёт `agent-effective-project-workflow-profile.v1`. Она не вызывает
модель, не запускает адаптер, не изменяет план и не пишет исходный код.

## Использование встроенного профиля

Для распространённого маршрута сначала просмотрите и проверьте встроенный
профиль, а затем создайте локальный файл:

```bash
agent-lifecycle project preset list
agent-lifecycle project preset inspect --preset research-review
agent-lifecycle project preset validate --preset research-review
agent-lifecycle project preset render \
  --preset research-review \
  --adapter <adapter-id> \
  --out .alk/project-profile.json
```

Созданный файл является обычным локальным профилем проекта. Для одной задачи
его можно не создавать и передать `--preset <идентификатор>` команде `start`.
Значения профиля имеют наименьший приоритет: явные параметры команды заменяют
локальные значения, а зафиксированный план может повысить требования. Полная
матрица и ограничения этапов приведены в разделе [профили рабочего процесса](workflow-presets.md).

## Запуск с профилем

Если в текущем проекте есть `.alk/project-profile.json`, команда `start` находит
его автоматически. Профиль может задать адаптер по умолчанию, поэтому простой
запуск выглядит так:

```bash
agent-lifecycle start --file task.md
agent-lifecycle start --text "Исследовать ошибку в кэше"
```

Профиль можно указать явно:

```bash
agent-lifecycle start \
  --project-profile .alk/project-profile.json \
  --file task.md
```

Для разового выбора адаптера передайте его в командной строке:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --project-profile .alk/project-profile.json \
  --mode research \
  --file research.md
```

Для воспроизводимого расширенного запуска без локальных настроек используйте
`--no-project-profile`:

```bash
agent-lifecycle start \
  --no-project-profile \
  --adapter <adapter-id> \
  --mode review \
  --file proposed-plan.md
```

## Поля профиля

Поля профиля намеренно ограничены:

| Поле | Назначение |
| --- | --- |
| `defaultAdapter` | Адаптер, используемый без `--adapter`. |
| `defaultMode` и `defaultRisk` | Режим подготовки и уровень риска по умолчанию. |
| `policies` | Относительные ссылки на существующие профили политики, маршрутизации, базовых ограничений, локальной модели и Review Mesh. |
| `stages` | Настройки этапов `intake`, `research`, `planning`, `review`, `implementation`, `audit` и `finalization`. |
| `principles` | Путь к принципам проекта, их отпечаток и `sourceOfTruth: false`; это контекст без полномочий на реализацию. |
| `guidanceRef` | Ограниченная относительная ссылка на руководство хоста для одного этапа. |

Настройки этапа могут выбрать существующий режим ALK, нейтральный класс модели,
режим Review Mesh и ограниченные значения `maxAttempts`, `maxInvocations` или
`maxWallSeconds`. В профиле нет сведений о провайдере, аккаунте, учётных данных,
секретах и системных инструкциях модели.

Пример:

```json
{
  "schemaVersion": "agent-project-workflow-profile.v1",
  "profileId": "checkout-project",
  "defaultAdapter": "<adapter-id>",
  "defaultMode": "auto",
  "defaultRisk": "S1",
  "policies": {
    "routingProfile": "profiles/model-routing-profile.v1.json",
    "baselineProfile": "profiles/review-mesh-profile.v1.json"
  },
  "stages": {
    "research": {
      "modelClass": "standard-code",
      "reviewMesh": "parallel-research-synthesis",
      "maxAttempts": 2,
      "maxWallSeconds": 1800,
      "guidanceRef": "docs/agent-research-guidance.md"
    },
    "implementation": {
      "risk": "S1",
      "reviewMesh": "implementation-audit-panel",
      "maxAttempts": 3
    }
  },
  "productionPromotionClaimed": false
}
```

### Необязательный мост тредов

Поле `threadBridge` включает ограниченный доступ к принадлежащим хосту тредам
для выбранных этапов. По умолчанию оно выключено и поддерживает `read`, `list`,
`send` и `create`. Для чтения и списка подтверждение оператора не требуется;
отправка и создание требуют подтверждение оператора и ключ идемпотентности.

```json
{
  "threadBridge": {
    "mode": "read-only",
    "operations": {
      "read": {"enabled": true, "scope": "explicit-target", "approval": "none", "blocking": "required"},
      "list": {"enabled": true, "scope": "project", "approval": "none", "blocking": "non-blocking"},
      "send": {"enabled": false, "scope": "explicit-target", "approval": "operator", "blocking": "required"},
      "create": {"enabled": false, "scope": "project", "approval": "operator", "blocking": "required"}
    },
    "phaseRules": {"research": {"read": {"enabled": true, "scope": "explicit-target"}}},
    "limits": {"maxImportedBytes": 32768, "maxImportedTokens": 2048}
  }
}
```

Политика моста задаёт разрешения и ограничения ресурсов, а нативный API тредов
остаётся в адаптере. Импортированный контекст не имеет полномочий менять план,
подтверждать приёмку или заменять доказательства. См. [страницу моста
тредов](optional-thread-bridge.md).

Ссылки остаются внутри корня проекта. Исключение `.alk/` предназначено для
локальных профилей модели и запуска внешнего инструмента. Загрузчик проверяет
компоненты пути и отклоняет обход корня, абсолютные пути, URL и выход через
символические ссылки.

## Полномочия и подтверждения

Настройки объединяются в таком порядке:

1. обязательные правила ALK;
2. зафиксированный план и соответствующий lock-файл;
3. явно переданные значения командной строки;
4. профиль проекта;
5. значения встроенного профиля.

Нижний уровень может задать значение по умолчанию, но не может ослабить уровень
риска, нижнюю границу качества, границы записи, обязательные проверки или
требования к подтверждениям из плана. Отпечаток профиля передаётся в стратегию
выполнения и проекции пакетов задачи.

Без активного профиля `start` сохраняет контракт
`agent-lifecycle-start-receipt.v1`. С активным профилем фасад возвращает
`agent-guided-action-receipt.v1`: в нём есть исходное подтверждение запуска,
сводка эффективного профиля, его отпечаток, ограниченная проекция руководства
для текущего этапа и следующее действие. Проекция содержит только метаданные
о руководстве и не копирует и не исполняет указанный файл. Это делает
управляемый путь наблюдаемым и сохраняет отдельные подтверждения атомарных
команд.

Профиль задаёт правила для внешнего инструмента, но не исполняет текст
руководства и не передаёт модели системные инструкции. Загрузка локальных
инструкций остаётся обязанностью адаптера. Полное описание цикла и атомарных
команд приведено в разделе [Настройка рабочего процесса и управления
выполнением](workflow-customization.md) и [справочнике CLI](cli.md).

Для долгосрочного контекста проекта и контролируемых изменений между версиями
плана см. [принципы проекта и дельты плана](project-principles-and-plan-deltas.md).
