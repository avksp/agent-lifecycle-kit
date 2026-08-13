# Управляемые сессии адаптеров

Управляемые сессии адаптеров дают оператору одну точку входа ALK для работы
через адаптеры, но не превращают ALK во вторую среду выполнения кодового агента.

Самая простая точка входа - `agent-lifecycle start`. Она выбирает приём задачи,
явную передачу зафиксированного запроса управляемому шагу или возобновление
сохранённой сессии, сохраняя прежние низкоуровневые контракты.

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
agent-lifecycle start --adapter codex --file task.md
agent-lifecycle start --adapter codex --mode research --text "Исследуй текущую архитектуру"
agent-lifecycle start --adapter codex --mode plan --file task.md --launch
agent-lifecycle start --adapter codex --mode implement --file adapter-run-request.json
agent-lifecycle start --adapter codex --resume <session-id>
agent-lifecycle host-launch inspect --profile .alk/host-launch/codex.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/codex.json
agent-lifecycle adapter launch-profile --adapter codex --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/codex.json

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

К обычному входу планирования можно добавить `--launch` только при состоянии
точной версии `PLANNING_ONLY_QUALIFIED`. Такой запуск завершается на проверке и
хранит только отпечатки. Поставляемые кандидаты пока не поддерживаются.
Подробнее: [запуск адаптера только для
планирования](planning-only-launch.md).

Для локального запуска зафиксированной реализации добавьте `--launch --host-launch-profile
.alk/host-launch/<adapter>.json` к полностью связанному вызову `start --mode
implement`. Структура профиля и полная команда приведены в разделе [локальный
запуск внешней команды](local-host-launch.md). Обычный текст не может попасть в
этот маршрут реализации.

Для точно проверенных версий Codex, Claude Code и OpenCode используйте
созданный профиль и обязательное подтверждение версии из раздела [запуск
зафиксированной задачи через проверенный профиль](qualified-host-launch.md).

`start` возвращает `agent-lifecycle-start-receipt.v1`. Сводка вложенного
результата содержит только устойчивые статусы, рекомендации и отпечатки
подтверждений; исходный текст задачи и локальные абсолютные пути исключены.
Режимы `auto`, `research`, `plan` и `review` ничего не выполняют. Режим
`implement` передаёт только полный структурированный зафиксированный запрос.
Возобновление принимает только сессию, записанную ALK, проверяет адаптер и
происхождение состояния и не подключается к диалогу внешнего инструмента.

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

## Управляемый запуск с учётом риска

Для зафиксированной задачи S1/S2 команда `start --risk auto` может определить
нейтральный класс модели и ограничения по токенам, числу обращений и времени.
Разрешение выполняется в два шага: `start --risk-profile-out <path>` только
создаёт привязанный отпечатками профиль без изменения состояния, а `workflow
task-start --risk-profile <path>` проверяет и записывает этот профиль перед
началом попытки. Затем `workflow task-result` требует подтверждённые хостом
данные расхода, включая `usage.invocations`.

Обычный текст и Markdown остаются черновыми: для них `--risk` носит только
рекомендательный характер и не разрешает выполнение или проверку расхода.
Полная последовательность команд и причины блокировки описаны в разделе
[Запуск с учётом риска](risk-aware-execution.md).

## Профиль запуска

Поле `managedLaunch` в дескрипторе адаптера объявляет один из статусов. Это
описательные данные, а не полномочие на общий запуск процесса:

| Статус | Значение |
| --- | --- |
| `SUPPORTED` | Дескриптор может содержать argv-шаблоны для отдельно проверенного локального маршрута. Общий маршрут библиотеки и CLI их не выполняет. |
| `WRAPPER_ONLY` | Обёртка или операторский сценарий может использовать управляемые сессии ALK, но прямой argv-запуск не заявляется. |
| `UNSUPPORTED` | Маршрут управляемого запуска не объявлен. |

Текущие встроенные адаптеры объявляют `WRAPPER_ONLY`. Так ALK может давать
доказательство управляемого жизненного цикла через свои команды, не заявляя
неподтверждённые прямые точки подключения или командные строки внешнего
инструмента. Проверенный локальный профиль может явно запустить один процесс
после проверки зафиксированных привязок и профиля риска, но этот локальный факт
не меняет публичный статус поддержки. `adapter session
start --launch` и прямой общий запуск через дескриптор всегда возвращают
`adapter-generic-launch-disabled` до создания процесса, независимо от статуса
профиля.

## Граница безопасности

Управляемые сессии адаптеров закрываются при сомнении и не раскрывают секреты:

- запуск использует argv-массивы с `shell: false`;
- общий выбор окружения принимает только точные имена, а шаблоны отклоняются;
- секреты провайдера выбираются только по allowlist из дескриптора или
  локальной политики проекта;
- общий механизм очистки удаляет из подтверждений проверенные формы секретов и
  локальных путей и фиксирует факт изменения значения;
- отслеживаемые файлы прямой конфигурации хоста не записываются;
- ALK не вставляет промпты в CLI хоста;
- ALK не разбирает телеметрию конкретного хоста в ядре;
- установка плагина сама по себе не является доказательством управляемого
  жизненного цикла.

Стабильные подтверждения: `agent-adapter-session-receipt.v1`,
`agent-managed-adapter-launch-receipt.v1`,
`agent-adapter-session-resume-receipt.v1`,
`agent-adapter-task-start-receipt.v1`,
`agent-adapter-task-run-request.v1`, `agent-lifecycle-start-receipt.v1` и
`agent-local-host-launch-profile-receipt.v1`.
Рекомендации групповой проверки используют
`agent-review-mesh-recommendation.v1`.

Для длинных управляемых сессий используйте страницу [снимки контекста и
восстановление после сжатия](context-checkpoints.md). Происхождение сессии и
снимка проверяются отдельно: восстановление не подключается к диалогу внешнего
инструмента и не выдаёт полномочий на реализацию.
