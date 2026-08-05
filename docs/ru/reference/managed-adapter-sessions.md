# Управляемые сессии адаптеров

Управляемые сессии адаптеров дают оператору одну точку входа ALK для работы
через адаптеры, но не превращают ALK во второй runtime кодового агента.

Есть три режима:

- интерактивная сессия: `adapter session start --adapter <id>` записывает
  сессию и возвращает `WAITING_FOR_TASK`; покрытие жизненного цикла не
  заявляется;
- приём задачи: `adapter task start --adapter <id> --file task.md` или
  `--text "..."` создаёт черновой вход для проверки. Для задач по ошибкам он
  может рекомендовать дополнительный профиль `Bug Forensics`, а для задач
  предварительного осмотра - отдельный аналитический шаг. Обычный текст не
  запускает выполнение;
- управляемый запуск: `adapter run --adapter <id> --state <state> --manifest
  <manifest> --task <task-id>` связывает сессию с зафиксированным состоянием
  workflow и возвращает следующий шаг жизненного цикла ALK.

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
обычного текста и Markdown receipt хранит только метку источника, отпечаток и
размер в байтах, но не исходный текст задачи. `--candidate-out <path>`
сохраняет черновой артефакт импорта для проверки.

`adapter run`, `adapter task start` на зафиксированном пути запуска и
`adapter session promote` по умолчанию показывают прогресс в stderr, потому
что это управляемые ALK-команды. JSON в stdout не меняется. Используй
`--progress-hook off`, чтобы выключить текстовый вывод, или `--progress-hook
receipt --progress-receipt <path>`, чтобы сохранить
`agent-progress-hook-receipt.v1`.

## Профиль запуска

Нативный запуск берётся из дескриптора. Поле `managedLaunch` в дескрипторе
адаптера объявляет один из статусов:

| Статус | Значение |
| --- | --- |
| `SUPPORTED` | В дескрипторе есть безопасные argv-шаблоны для управляемого запуска. |
| `WRAPPER_ONLY` | Обёртка или операторский сценарий может использовать управляемые сессии ALK, но нативный argv-запуск не заявляется. |
| `UNSUPPORTED` | Маршрут управляемого запуска не объявлен. |

Текущие встроенные адаптеры объявляют `WRAPPER_ONLY`. Так ALK может давать
доказательство управляемого жизненного цикла через свои команды, не заявляя
неподтверждённые native hooks или командные строки хоста.

## Граница безопасности

Управляемые сессии адаптеров закрываются при сомнении и не раскрывают секреты:

- запуск использует argv-массивы с `shell: false`;
- секреты провайдера выбираются только по allowlist из дескриптора или
  локальной политики проекта;
- значения секретов не попадают в receipts;
- отслеживаемые файлы нативной конфигурации хоста не записываются;
- ALK не вставляет prompts в host CLI;
- ALK не разбирает host-specific telemetry в core;
- установка plugin сама по себе не является доказательством управляемого
  жизненного цикла.

Стабильные receipts: `agent-adapter-session-receipt.v1`,
`agent-managed-adapter-launch-receipt.v1`,
`agent-adapter-session-resume-receipt.v1`,
`agent-adapter-task-start-receipt.v1` и
`agent-adapter-task-run-request.v1`.
