# Управляемые сессии адаптеров

Управляемые сессии адаптеров дают оператору одну точку входа ALK для работы
через адаптеры, но не превращают ALK во вторую среду выполнения кодового агента.

Есть три режима:

- интерактивная сессия: `adapter session start --adapter <id>` записывает
  сессию и возвращает `WAITING_FOR_TASK`; покрытие жизненного цикла не
  заявляется;
- приём задачи: `adapter task start --adapter <id> --file task.md` или
  `--text "..."` создаёт черновой вход для проверки. Для задач по ошибкам он
  может рекомендовать дополнительный профиль расследования ошибок, а для задач
  предварительного осмотра - отдельный аналитический шаг. Также он может
  добавить рекомендательную групповую проверку, если дополнительные проверяющие
  могут повысить качество планирования, исследования или аудита. Обычный текст не
  запускает выполнение;
- управляемый запуск: `adapter run --adapter <id> --state <state> --manifest
  <manifest> --task <task-id>` связывает сессию с зафиксированным состоянием
  рабочего цикла и возвращает следующий шаг жизненного цикла ALK.

Возобновление проверяет происхождение. `adapter session resume` сравнивает
сохранённую сессию с запрошенным адаптером, состоянием workflow и задачей.
Несовпадение возвращает `agent-adapter-session-resume-receipt.v1` со статусом
`BLOCKED`.

## Команды

```bash
agent-lifecycle adapter session start --adapter codex
agent-lifecycle adapter session start --adapter codex --launch
agent-lifecycle adapter session status --session <session-id>
agent-lifecycle adapter session promote \
  --session <session-id> \
  --state <workflow-state.json> \
  --task <task-id>
agent-lifecycle adapter session resume \
  --session <session-id> \
  --state <workflow-state.json> \
  --task <task-id>
agent-lifecycle adapter task start --adapter codex --file task.md
agent-lifecycle adapter task start --adapter codex --task-text "Исправь регрессию"
agent-lifecycle adapter task start --adapter codex --file adapter-run-request.json
agent-lifecycle adapter run \
  --adapter codex \
  --state <workflow-state.json> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --task <task-id>
```

`adapter task start` возвращает `agent-adapter-task-start-receipt.v1`. Для
обычного текста и Markdown подтверждение хранит только метку источника, отпечаток и
размер в байтах, но не исходный текст задачи. Поле
`reviewMeshRecommendation` носит рекомендательный характер и само не включает
обязательную перепроверку. `--candidate-out <path>` сохраняет черновой артефакт
импорта для проверки.

`adapter run`, `adapter task start` на зафиксированном пути запуска и
`adapter session promote` по умолчанию показывают прогресс в stderr, потому
что это управляемые ALK-команды. JSON в stdout не меняется. Используй
`--progress-hook off`, чтобы выключить текстовый вывод, или `--progress-hook
receipt --progress-receipt <path>`, чтобы сохранить
`agent-progress-hook-receipt.v1`.

## Профиль запуска

Прямой запуск берётся из дескриптора. Поле `managedLaunch` в дескрипторе
адаптера объявляет один из статусов:

| Статус | Значение |
| --- | --- |
| `SUPPORTED` | В дескрипторе есть безопасные argv-шаблоны для управляемого запуска. |
| `WRAPPER_ONLY` | Обёртка или операторский сценарий может использовать управляемые сессии ALK, но прямой argv-запуск не заявляется. |
| `UNSUPPORTED` | Маршрут управляемого запуска не объявлен. |

Текущие встроенные адаптеры объявляют `WRAPPER_ONLY`. Так ALK может давать
доказательство управляемого жизненного цикла через свои команды, не заявляя
неподтверждённые прямые hooks или командные строки хоста.

## Граница безопасности

Управляемые сессии адаптеров закрываются при сомнении и не раскрывают секреты:

- запуск использует argv-массивы с `shell: false`;
- секреты провайдера выбираются только по allowlist из дескриптора или
  локальной политики проекта;
- значения секретов не попадают в подтверждения;
- отслеживаемые файлы прямой конфигурации хоста не записываются;
- ALK не вставляет промпты в CLI хоста;
- ALK не разбирает телеметрию конкретного хоста в ядре;
- установка плагина сама по себе не является доказательством управляемого
  жизненного цикла.

Стабильные подтверждения: `agent-adapter-session-receipt.v1`,
`agent-managed-adapter-launch-receipt.v1`,
`agent-adapter-session-resume-receipt.v1`,
`agent-adapter-task-start-receipt.v1` и
`agent-adapter-task-run-request.v1`. Рекомендации групповой проверки используют
`agent-review-mesh-recommendation.v1`.
