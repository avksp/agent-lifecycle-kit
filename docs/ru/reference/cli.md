# Справочник команд

## Полномочия команд рабочего цикла

Для всех интеграций используйте `workflow run` и команды `workflow task-*`.
Прежняя поверхность контролируемого runner удалена в 2.0. Исторические
артефакты runner обрабатываются только явной read-only командой
`workflow migrate-runner-artifact`, описанной в разделе [Миграция runner](../guides/runner-migration-2.md).
Преобразованная запись является только evidence и не может менять состояние
workflow или заменять приёмку/финализацию.

Основная команда называется `agent-lifecycle`. Она возвращает структурированный
JSON, чтобы результат можно было проверять автоматически.

Выбор между простой командой `start` и отдельными переходами жизненного цикла,
а также работа нескольких агентов, локальные настройки моделей, промпты,
тайм-ауты и повторы описаны в разделе [Настройка рабочего процесса и управления
выполнением](workflow-customization.md).

Для первой установки и короткого маршрута используйте руководство [Установка
ALK и первый запуск](../guides/install-and-first-run.md). Указатель команд по
задачам находится на странице [Команды по задачам](../guides/commands-by-task.md).

## Установка

Поддерживаются Python 3.11-3.14. Установите точную версию из официального
[проекта в PyPI](https://pypi.org/project/agent-lifecycle-kit/):

```bash
python -m pip install agent-lifecycle-kit==2.13.0
```

## Идентичность подтверждений задачи

Полномочные маршруты `workflow task-result`, `task-accept`, `task-rework` и
`task-review-apply` закрываются с отказом, если результат не содержит непустые
`actor` и `actorRunId`, а ревью не содержит непустой `reviewId`. Идентификатор
и запуск рецензента должны отличаться от идентичности исполнителя. Некорректное
подтверждение возвращает типизированную ошибку `task-result-invalid`,
`task-review-invalid` или `task-review-self-certification` до изменения байтов
состояния workflow или журнала событий. Исторические подтверждения остаются
читаемыми, но не обходят текущую приёмку.

## Контракты ошибок и ресурсов

Корневой CLI возвращает `agent-lifecycle-error.v1` с кодом выхода `2` для
ожидаемых ошибок ввода-вывода, декодирования, глубины JSON и непредвиденных
ошибок. JSON очищается и не содержит трассировку или локальный абсолютный путь.
Поведение библиотечных исключений и `KeyboardInterrupt`/`SystemExit` не
меняется. См. [контракт ошибок CLI](cli-errors.md).

## Публичные локаторы и редакция

URL подтверждений проходят офлайн-контракт
`agent-public-evidence-locator.v1`. Разрешены только HTTP(S); хосты
нормализуются, а учётные данные, опасные схемы, секреты и локальные пути
отклоняются или редактируются. См. [публичные локаторы и редакцию](public-locators-and-redaction.md).

Встроенные профили загружаются через `importlib.resources`, поэтому команды
работают из установленного wheel вне исходного дерева. Одноимённый файл в
текущей папке не может подменить встроенный профиль, а явно переданный путь
сохраняет приоритет. Поддерживаемая поверхность импорта перечислена в
[справочнике API Python](python-api.md).

## Внешние проверки проекта

Необязательные проверки проекта позволяют записать ограниченное подтверждение
архитектуры или зависимостей:

```bash
agent-lifecycle quality external-check \
  --check-id import-boundaries \
  --plan-digest <64-hex-digest> \
  --plan-lock-digest <64-hex-digest> \
  --operation-id external-check-001 \
  --out work/external-check.json
```

Доступны встроенные профили `import-boundaries`, `module-dependencies` и
`declared-dependencies`. Установите выбранный анализатор в проекте; ALK не
добавляет его в runtime-зависимости. Результат связан с исходниками,
конфигурацией и планом, сырой вывод не сохраняется, а отсутствующий или
неполный анализатор возвращает `UNAVAILABLE`. Результат не может принять,
заморозить или опубликовать что-либо. См. [внешние проверки проекта](external-verification-checks.md).

## Ограниченные задания внешних инструментов

Используйте `adapter external-job` только для необязательной работы адаптера,
которой нужны адресуемая попытка, ограниченная отмена или артефакты только с
метаданными и дайджестами:

```bash
agent-lifecycle adapter external-job run --request job-request.json --out work/job.json -- <argv...>
agent-lifecycle adapter external-job status --request job-request.json --out work/job-status.json
agent-lifecycle adapter external-job cancel --request job-request.json --out work/job-cancel.json
```

По умолчанию попытки используют приватное создаваемое один раз состояние в
`.alk/external-jobs`. Тайм-аут, отмена, ошибка очистки, живые дочерние процессы,
запись после завершения, `NO_FINAL_VERDICT` и превышенные лимиты не дают эффекта
приёмки. ALK не добавляет клиент провайдера, сетевой вызов, daemon или новые
полномочия workflow. См. [ограниченные задания внешних
инструментов](external-tool-jobs.md).

## Необязательный анализ безопасности

Профиль безопасности по умолчанию выключен, а импортированные находки остаются
недоверенными:

```bash
agent-lifecycle quality security-profile --out work/security-profile.json
agent-lifecycle import security-findings \
  --source findings.sarif \
  --expected-source-revision <revision> \
  --out work/security-findings.json
agent-lifecycle quality security-finding-check \
  --candidate work/security-findings.json \
  --expected-source-revision <revision> \
  --out work/security-findings-validation.json
```

Для ограниченного отчёта только для чтения используйте `report
security-analysis --finding <path> --profile`. Импортированная находка или
профиль не могут начать выполнение. Для доработки высокой серьёзности на
границе приёмки задачи требуется новое независимое назначение проверки;
свидетельство только исполнителя отклоняется с кодом
`security-analysis-verification-required`. См. [необязательный профиль анализа
безопасности](security-analysis-profile.md).

## Производительность и подтверждения ресурсов

В релизе 1.78 команда `version` быстрее запускается благодаря ленивой загрузке
групп команд. Измерительный контур и жёсткие пределы описаны в разделе
[бюджеты производительности и ресурсов](performance-and-resource-budgets.md).
Время является справочным, если план не установил иное; проверки безопасности,
совместимости, ресурсов и отказа по умолчанию остаются обязательными.

`agent-lifecycle metrics phase-resources --input <путь> --out <путь>`
преобразует явный `agent-phase-resource-input.v1` в ограниченный
`agent-phase-resource-measurement.v1`. Команда `agent-lifecycle metrics
release-accounting --release-id <id> --artifact <путь> --project-root <путь>
--out <путь>` объединяет уникальные локальные измерения в
`agent-release-accounting.v1`. Обе команды только создают выходной файл и не
вызывают модель, сеть или процесс хоста. Отсутствующая телеметрия остаётся
`UNAVAILABLE` с null-значением; `elapsedWallMs` и `computeMs` не смешиваются.
Подробности приведены в разделе [учёт ресурсов релиза](release-accounting.md).

## Необязательный контроль жизненного цикла адаптера

`agent-lifecycle adapter lifecycle-control-check` проверяет локальную политику
или переданные запрос, решение, события и подтверждение контроля, не запуская
хост. `agent-lifecycle adapter event-check` проверяет переносимый поток событий.
Эти команды создают данные для проверки, но не повышают уровень адаптера и не
меняют настройки хоста.

Операционные поля называются `declaredLevel`, `supportedLevel`,
`qualifiedLevel` и `qualificationStatus`. Комплектные адаптеры сейчас публикуют
`GUIDANCE_ONLY` и `NO_RECOMMENDATION`, а управляемый запуск остаётся
`WRAPPER_ONLY`. См. [необязательный контроль жизненного цикла адаптера](../adapters/lifecycle-control.md).

## Основа

- `agent-lifecycle version`: версия пакета.
- `agent-lifecycle diagnose --no-install-plans`: безопасная проверка
  готовности текущего дерева.
- `agent-lifecycle schema list`: список публичных схем.
- `agent-lifecycle tier resolve --request <request.json>`: определяет уровень
  SDD и повторяемый отпечаток структурированного запроса.
- `agent-lifecycle conformance`: зарезервированный раздел совместимости. У него
  нет исполняемого сценария проверки; используйте `agent-lifecycle adapter
  validate`, осмотр адаптера и релизные средства проверки совместимости.

## Планирование

- `agent-lifecycle specification`: проверки спецификации и проверки
  завершения.
- `agent-lifecycle plan check`: проверка плана и файла блокировки. Флаг
  `--require-completeness` включает структурную проверку полноты выбранного SDD
  уровня.
- `agent-lifecycle plan lock-create --manifest <путь> --review <путь>
  [--repository-root <путь>]`: проверяет финальный рассмотренный пакет и создаёт
  канонический `agent-plan-lock.v2`. Команда записывает файл только после всех
  проверок пакета и завершается отказом вместо замены существующего
  `plan.lock.json`.
- `agent-lifecycle plan verify`: формирует безопасный отчёт проверки пакета
  плана: манифеста, трассируемости, lock-файла и целостности пакета. Команда не
  выполняет команды из плана и не даёт полномочий на изменения.
- `agent-lifecycle plan completeness-check`: возвращает
  `agent-plan-completeness-validation.v1` с конкретными блокерами по выбранному
  уровню.
- `agent-lifecycle plan acceptance-check`: проверка трассируемости критериев
  приёмки.
- `agent-lifecycle plan finding-check propose|validate|accept|evidence|transition`:
  связывает принятую находку с существующей детерминированной проверкой.
  Предложения остаются рекомендательными, идентичность проверки не содержит
  исполняемого текста, а подтверждение фиксирует только чтение. См. [связывание
  находки с проверкой](finding-check-adoption.md).
- `agent-lifecycle import plan/check`: перевод файла или папки Markdown в
  черновой план-кандидат. Флаг `--dialect openspec|spec-kit|bmad|spec-kitty`
  выбирает профиль OpenSpec, Spec Kit, BMAD или Spec Kitty; результат требует
  проверки и заморозки перед реализацией.
- навык `issue-to-spec`: перевод внешних тикетов в черновой вход спецификации
  ALK.
- `agent-lifecycle quality template-list/template-check`: просмотр и проверка
  черновых шаблонов задач.
- Частые сценарии собраны в `docs/ru/lifecycle-cookbook.md`: исследование,
  проверка Markdown, проверка изменений и аудит реализации.

Для передачи плана другому проверяющему используйте `plan verify` с манифестом,
папкой пакета, критериями приёмки, lock-файлом и состоянием рабочего цикла.
Точная команда и правила отказа описаны в разделе [проверка целостности
плана](plan-verification.md).

## Профиль проекта

- `agent-lifecycle project profile init --adapter <adapter-id> --out .alk/project-profile.json`:
  создаёт минимальный локальный файл настроек и при необходимости записывает
  адаптер по умолчанию. Без `--adapter` значение можно добавить в файл или
  передавать в каждой команде.
- `agent-lifecycle project profile check`: проверяет и разрешает найденный
  `.alk/project-profile.json`.
- `agent-lifecycle project profile check --manifest <plan> --lock <lock>`:
  связывает профиль с полномочиями плана и возвращает эффективный профиль.
  Для разового безопасного изменения можно добавить `--adapter`, `--mode` или
  `--risk`.
- `agent-lifecycle project profile explain --profile <profile> --preset <id>
  --manifest <plan> --lock <lock> --descriptor <descriptor>
  --capability-manifest <manifest>`: возвращает только для чтения
  `agent-effective-configuration-explanation.v1` с происхождением полей,
  ограничениями зафиксированного плана и применимостью контроля для конкретной
  операции. Можно добавить ограниченные `--adapter`, `--mode`, `--risk`,
  `--stage-risk` или `--stage-mode`. Отсутствующая или устаревшая линия
  capability возвращает `UNAVAILABLE` и не повышает заявление. См. [объяснение
  эффективной конфигурации](effective-configuration.md).
- `agent-lifecycle start --file <path>` или `--text <text>`: использует найденный
  профиль, если в нём задан адаптер по умолчанию. Флаг `--project-profile <path>`
  выбирает профиль явно, а `--no-project-profile` отключает автоматический поиск.

Профиль является локальным слоем настроек проекта. Зафиксированный план и его
lock-файл остаются источником полномочий для риска, качества, границ записи,
гейтов и подтверждений. Подробнее: [Профиль рабочего процесса проекта](project-workflow-profile.md).

## Профили рабочего процесса

Встроенные профили помогают выбрать ограниченные настройки для распространённого
маршрута:

```bash
agent-lifecycle project preset list
agent-lifecycle project preset inspect --preset feature-implementation
agent-lifecycle project preset validate --preset feature-implementation
agent-lifecycle project preset render \
  --preset research-review \
  --adapter <adapter-id> \
  --out .alk/project-profile.json
```

Команды `project preset` читают локальные версионируемые данные, возвращают
устойчивый JSON, не вызывают модель и не запускают внешний инструмент. `render`
пишет только в явно указанный путь и не перезаписывает существующий файл. Для
одной задачи можно использовать `start --preset <идентификатор>` без создания
профиля. Значения профиля являются настройками по умолчанию и уступают явно
переданным значениям командной строки и профиля проекта; зафиксированный план
может повысить требования, но профиль не может их ослабить. См. [профили
рабочего процесса](workflow-presets.md).

Проверьте файл принципов командой `agent-lifecycle project principles check
--file <path>`. Сравните две версии плана командой `agent-lifecycle plan delta
--before <manifest> --after <manifest>`, а созданный отчёт проверьте командой
`agent-lifecycle plan delta-check --delta <delta.json>`. Обе операции только
читают исходные файлы и возвращают устойчивые JSON-контракты.

## Предметный язык проекта

Необязательный словарь проверяется командой
`agent-lifecycle project language check --file <path> --project-root .`, а
аудит без изменений выполняется командой
`agent-lifecycle project language audit --file <path> --term-id <id>
--changed-path <path>`. Для связывания изменений терминов с дельтой плана
добавьте к `plan delta` оба флага `--language-before <path>` и
`--language-after <path>`. Словарь является контекстом только для чтения: он
не выдаёт полномочия записи и не заменяет спецификацию или зафиксированный
план. См. [предметный язык проекта](project-domain-language.md).

## Выполнение

- `agent-lifecycle start --adapter <id> (--file task.md | --text "..." |
  --resume <session-id>)`: единая команда над приёмом задачи, передачей
  зафиксированного запроса управляемому шагу и возобновлением сохранённой сессии
  ALK. Псевдонимы источников: `--task-file` и `--task-text`; требуется ровно
  одно действие. Режим `--mode auto|research|plan|review|implement` по умолчанию
  равен `auto`. Обычный ввод и все режимы, кроме явного `implement`, ничего не
  выполняют. Для `implement` нужен структурированный зафиксированный запрос с
  полной привязкой состояния, манифеста, lock-файла, задачи, операции и ревизий.
  Команда возвращает `agent-lifecycle-start-receipt.v1` и не принимает
  `--resume` за идентификатор диалога внешнего инструмента. Внешний процесс по
  умолчанию не запускается. Для него полностью связанный вызов `implement`
  должен также содержать `--launch --host-launch-profile
  .alk/host-launch/<adapter>.json`; см. [локальный запуск внешней
  команды](local-host-launch.md).
- `agent-lifecycle start --adapter <id> --mode plan --file task.md --launch`:
  запрос одного внешнего процесса только для планирования с точной привязкой к
  версии. Внешнее подтверждение сохраняет действие `DRAFT_PLAN_REVIEW`, а
  вложенное подтверждение фиксирует запуск процесса и модели. Поставляемые
  кандидаты пока имеют состояние `PLANNING_ONLY_UNSUPPORTED`, поэтому маршрут
  завершается безопасным отказом до реальной квалификации. Подробнее: [запуск
  адаптера только для планирования](planning-only-launch.md).
- `agent-lifecycle host-launch inspect/preflight --profile <путь>`: проверяет
  локальный профиль пользователя без создания процесса либо явно выполняет
  одну ограниченную проверку версии. Эти команды не разрешают выполнение
  задачи.

- `agent-lifecycle workflow run`: проверяет связь зафиксированного плана и
  сохранённого состояния, затем возвращает следующий шаг для хоста без записи
  в состояние и без запуска модели. Добавьте `--progress-hook stderr`, чтобы
  показать прогресс в stderr, или `--progress-hook receipt --progress-receipt
  <path>`, чтобы сохранить `agent-progress-hook-receipt.v1` без изменения JSON
  в stdout.
- `agent-lifecycle workflow continue`: по умолчанию без изменения состояния
  вычисляет следующий существующий переход workflow. Для применения повторите
  те же входы с `--apply`, вычисленной ревизией состояния и дайджестом действия.
  Для объявленной детерминированной последовательности добавьте
  `--until-blocked`, `--apply`, входной пакет, явные положительные лимиты, lock
  и выходной receipt; пакетный режим остановится до внешних полномочий.
  Подробности: [продолжение workflow](workflow-continuation.md).
- `agent-lifecycle workflow init --state <путь> --run-id <id> --package-id
  <id>`: создаёт один приватный несвязанный файл
  `agent-workflow-state.v4` и не заменяет существующее состояние.
- `agent-lifecycle workflow state-migrate --state <путь> --operation-id <id>
  --expected-revision <n> --source-revision <sha>`: выполняет одну явную
  миграцию v3 в v4 с отказом при любой неоднозначности.
- `agent-lifecycle workflow authorize`: принимает одно неистёкшее
  подтверждение с точной связью запуска, плана и исходной ревизии и переводит
  запуск из `AWAITING_AUTHORIZATION` в `READY`. Для `PLAN_ONLY` команда
  отклоняется.
- `agent-lifecycle workflow external-pause` и `external-resume`: ставят
  поддерживаемый этап выполнения или финального аудита на ожидание одного
  действия хоста и возобновляют его только по соответствующему подтверждению.
  Обе операции проверяют связь запуска, плана и исходной ревизии, ожидаемую
  ревизию состояния и идемпотентность.
- `agent-lifecycle workflow task-start`: открывает ограниченную попытку задачи.
  Параметр `--strategy <receipt>` вместе с точными входами
  `--strategy-risk`, политики, дескриптора, манифеста возможностей и профиля
  проекта принимает полностью связанную стратегию. Переход заново вычисляет
  все отпечатки и блокирует устаревшие или неполные входы до записи.
- `agent-lifecycle workflow task-snapshot`: без изменения состояния вычисляет
  текущий набор файлов задачи и отпечатки их содержимого по Git. Объект `claim`
  из результата нужно поместить в результат задачи перед `task-result`.
  Параметры `--manifest`, `--lock`, `--phase-packet-purpose` и
  `--phase-packet-out` задаются только вместе и создают отдельный ограниченный
  `agent-phase-packet.v1` для реализации, аудита задачи или доработки.
- `agent-lifecycle workflow validation-select --state ... --task ...
  --manifest ... --lock ... --snapshot ... [--out ...]`: выбирает ID
  зафиксированных проверок без запуска команд и изменения состояния. Для
  legacy-плана и защищённых путей консервативно выбирается `RELEASE_FULL`.
- `agent-lifecycle workflow task-result`: сохраняет результат реализации.
- `agent-lifecycle workflow task-rework`: после решения `REWORK` независимой
  проверки сохраняет данные текущей попытки и переводит задачу в
  `REMEDIATING`. Для каждой открытой находки укажите отдельный `--finding-id`;
  зафиксированный план должен разрешать ещё одну попытку.
- `agent-lifecycle workflow task-accept`: принимает проверенную задачу.
- `agent-lifecycle workflow task-review-apply`: применяет один результат
  независимой проверки. Это канонический маршрут для `ACCEPTED`, `REWORK`,
  `CONTRACT_CHANGE` и `BLOCKED`; для `REWORK` укажите отдельный
  `--finding-id` для каждой открытой находки.
- `agent-lifecycle workflow final-audit-outcome`: применяет вердикт
  независимого финального аудита. `ACCEPTED` разрешает финализацию, `REWORK`
  архивирует только названные принятые задачи и открывает ограниченную
  доработку, `CONTRACT_CHANGE` ждёт новый зафиксированный план, а `BLOCKED`
  ждёт объявленное внешнее действие. План, бюджет повторов и полномочия не
  изменяются автоматически.
- `agent-lifecycle workflow`: остальные переходы жизненного цикла, отчёты задач и
  финальное подтверждение. Для запусков с обязательной проверкой причинной
  цепочки `workflow finalize` принимает
  `--proof-integrity <proof-integrity.json>`; для обязательного решения
  завершения принимает `--completion-gate-receipt <completion-gate.json>`.
  Если план требует аудит реализации, `workflow task-accept` принимает
  `--implementation-audit <implementation-audit.json>`, а `workflow finalize`
  принимает `--final-implementation-audit <final-implementation-audit.json>`.
  Для плана с обязательной групповой проверкой на финальном аудите
  `workflow finalize` принимает `--review-mesh-quorum <path>`. План с
  включённой лестницей проверок также требует `--release-full-receipt
  <release-full.json>` с точным lineage plan, lock, source, дерева и каталога.
- Управляемый вывод прогресса поддерживают только `workflow run`,
  `workflow task-result`, `workflow task-accept`, `workflow task-review-apply`,
  `workflow final-audit-outcome` и `workflow finalize`.
  `ALK_PROGRESS_HOOK=stderr` можно использовать в обёртках; установка плагина
  сама по себе не доказывает полный жизненный цикл.
- `agent-lifecycle workflow run`: текущий маршрут выполнения с привязкой к
  замороженному плану и состоянию.
- `agent-lifecycle workflow migrate-runner-artifact`: преобразование одного
  исторического артефакта runner в приватную read-only неавторитетную запись.
- `agent-lifecycle strategy resolve --manifest ... --lock ... --state ...
  --task ... --operation-id ... --expected-revision ... --source-revision ...
  --adapter ... --out ...`: записывает одну нейтральную стратегию выполнения
  без изменения состояния. Для S1/S2 нужен подходящий `--host-model-profile`.
- `agent-lifecycle start ... --strategy-out <path>` и
  `agent-lifecycle adapter task start ... --strategy-out <path>`: создают один
  create-only артефакт стратегии для точной следующей попытки в управляемом
  маршруте. Истинное `automaticAdoptionEligible` означает только пригодность
  маршрута; артефакт содержит `modelCallsStarted: false` и не даёт полномочий
  реализации, приёмки или завершения.
- `agent-lifecycle workflow continue ... --strategy <path>
  --strategy-descriptor <path> --strategy-capability-manifest <path>
  --strategy-project-profile <path>`: проецирует или применяет запуск задачи
  через тот же артефакт. Команда по-прежнему требует защиту проекции и не может
  понизить проверку или заменить финальную `RELEASE_FULL`.
- `agent-lifecycle task compile --manifest ... --strategy ...`: передаёт
  проверенную стратегию в связанный полный пакет, не меняя полномочия плана.
- `agent-lifecycle task compile-small`: пакеты для маленьких моделей с
  контрактом результата и компактным артефактом контекста. Параметр
  `--strategy` требует допустимый компактный маршрут.

## Проверка качества

- `agent-lifecycle benchmark evaluate`: сравнивает переданный результат со
  встроенным набором детерминированных эталонных задач и создаёт
  `agent-reference-task-evaluation.v1` без вызова модели или внешнего инструмента.
- `agent-lifecycle benchmark compare --baseline ... --candidate ...`:
  сравнивает два артефакта, начиная с качества, и показывает разницу токенов,
  обращений, повторов, циклов исправления и времени с учётом достоверности.
- `agent-lifecycle benchmark sample`: создаёт ограниченную воспроизводимую
  выборку по семейству, уровню и форме задачи.
- `agent-lifecycle benchmark receipt-check --receipt ...`: проверяет внешнюю
  запись выполнения без запуска указанного исполнителя. В техническом имени
  схемы `receipt` сохранено ради совместимости.
- `agent-lifecycle benchmark qualify --receipt ...`: применяет минимальные
  требования к задачам, повторам, группам и подтверждениям качества для одного
  маршрута.
- `agent-lifecycle benchmark compare-routes --baseline ... --candidate ...`:
  сравнивает варианты выполнения, для которых набрано минимальное количество
  подтверждений, и явно показывает изменения среды и оценщика.

Описание квалификации capability структурированного результата находится в
[отдельном справочнике](structured-result-qualification.md). Используются
существующие benchmark receipt и помощники Python-контрактов; в 1.89 не
добавляется провайдерская команда для формата ответа. Квалификация остаётся
рекомендательной и не может принять задачу или повысить уровень поддержки
адаптера.

- `agent-lifecycle audit`: проверка плана, реализации и вердиктов.
- `agent-lifecycle audit implementation`: структурированный отчёт
  `agent-implementation-audit-report.v1` по результату задачи и независимой
  проверке. Если зафиксированный план требует групповую проверку для аудита
  реализации, используйте `--review-mesh-quorum <path>`.
- `agent-lifecycle audit delta`: создаёт read-only и command-free
  `agent-rework-delta-audit-receipt.v1` для соседних повторных попыток.
  Неопределённое или устаревшее влияние выбирает `FULL_AUDIT_REQUIRED`; этот
  артефакт никогда не принимает задачу.
- `agent-lifecycle audit final-implementation`: итоговый отчёт
  `agent-final-implementation-audit.v1` перед финальным подтверждением
  рабочего цикла.
- `agent-lifecycle audit package --plan-dir <папка>`: проверка папки плана и,
  при указании `--state <путь>`, объединение аудитов реализации. Для строгой
  проверки готовой передачи используйте `--require-frozen
  --require-implementation --strict`; список отчётов можно задать несколькими
  параметрами `--report <путь>`.
- `agent-lifecycle quality`: дополнительные проверочные наборы.
- `agent-lifecycle quality bug-recipe-list/bug-recipe-check`: просмотр
  переиспользуемых рецептов профиля расследования ошибок, которые используют
  существующие артефакты.

## Расход и настройки

- `agent-lifecycle metrics`: отчёты о расходе, экспорт использования и
  рекомендации по режиму.
- `agent-lifecycle metrics cost-report`: формирует отчёт затрат по явным
  JSON-артефактам. Для измерения фаз используются объявленные итоги токенов и
  шагов, а не оценка по размеру JSON.
- `agent-lifecycle metrics phase-resources --input <путь> --out <путь>`:
  проверяет и сохраняет ограниченное измерение фаз без замены существующего
  артефакта.
- `agent-lifecycle metrics release-accounting --release-id <id> --artifact
  <путь> --project-root <путь> --out <путь>`: объединяет не более 64 уникальных
  локальных источников в представления процесса ALK, реализации, аудита и
  исправлений после аудита. `--artifact` можно повторять; `--provenance`
  сравнивает объявленные и наблюдаемые идентичности без заявления аттестации.
- `agent-lifecycle metrics outcome-index/quality-signals/learn-recommend`:
  рекомендательное обучение по локальным артефактам без автоматического
  применения.
- `agent-lifecycle metrics audit-sample --receipt <путь> --out <путь>`:
  собирает ограниченную выборку из подтверждений проверки, использования и
  ресурсов процесса.
- `agent-lifecycle metrics audit-report --sample <путь> --candidate-profile <путь> --out <путь>`:
  рассчитывает качество, время, токены и ресурсы, проверяет кандидатов на
  эталонных задачах и выдаёт рекомендацию. Флаг `--terminal` показывает
  краткий отчёт для оператора.
- `agent-lifecycle metrics audit-efficiency --input <путь> --comparison <путь> --out <путь>`:
  проверяет явные привязанные к lineage входы учёта и создаёт рекомендательные
  метрики эффективности без снижения quality floor. `--comparison` можно
  повторять; один пример возвращает `NO_COMPARISON`, а `UNAVAILABLE` не
  превращается в ноль.
- `agent-lifecycle metrics audit-proposal --report <путь> --out <путь>`:
  фиксирует решение оператора по рекомендации. Флаг `--approved` следует
  использовать только после просмотра отчёта; замороженный план не меняется.
- `agent-lifecycle metrics audit-apply --proposal <путь> --out <путь>`:
  создаёт новый подтверждённый профильный артефакт. Манифест и lock-файл
  нельзя использовать как путь вывода.

Полный порядок сбора подтверждений, проверки на эталонных задачах и
подтверждения решения описан в разделе [оптимизация проверок по подтверждённым
данным](audit-optimization.md).
Происхождение, достаточность выборки и семантика измеренных расходов описаны в
разделах [независимость подтверждений](evidence-independence.md) и
[эффективность проверки](review-efficiency.md).
- `agent-lifecycle metrics usage-export`: экспорт сессий, отпечатков
  подтверждений, токенов, ресурсов, длительности, решений по бюджету и
  необязательного `cost_usd`, если его сообщает тарифицируемый хост.
- `agent-lifecycle metrics execution-report --receipt <path> --out <path>`:
  объединяет обезличенные квитанции выполнения процессов в локальный отчёт о
  ресурсах. Для нескольких запусков повторите `--receipt`; флаг
  `--operation-id` связывает отчёт с одной операцией.
- `agent-lifecycle policy`: адаптивные решения, артефакты правил запуска и
  рекомендательные предложения по настройке правил.
- `agent-lifecycle review-mesh profile`: создаёт профиль групповой проверки с
  лимитами по токенам/ресурсам и нейтральными классами моделей.
- `agent-lifecycle review-mesh recommend`: анализирует текст задачи, файл
  задачи, артефакт приёма задачи или манифест плана и возвращает
  `agent-review-mesh-recommendation.v1`. Полученный артефакт только рекомендует
  режим: он не создаёт назначения, не запускает адаптеры и не включает
  обязательные контрольные точки.
- `agent-lifecycle review-mesh template-list/prepare`: показывает встроенные
  шаблоны для оператора и готовит локальный профиль с пакетами назначений из
  артефакта приёма задачи, манифеста или handoff. `prepare` записывает
  `agent-review-mesh-prepare-receipt.v1`, не вызывает провайдеров и не
  запускает CLI проверяющих.
- `agent-lifecycle review-mesh assign/import-result/synthesize/quorum`:
  создаёт пакеты назначений для выполнения на стороне хоста, импортирует
  обезличенный результат проверяющего, объединяет выводы и формирует артефакт
  кворума. Эти команды не вызывают модели и не запускают CLI хоста.

## Исследовательские материалы

- `agent-lifecycle research validate --package <путь> [--snapshot SOURCE_ID=PATH] --out <путь>`:
  проверяет локальный пакет `agent-research-evidence-package.v1`, при наличии
  снимков связывает цитаты с явными фрагментами UTF-8, анализирует происхождение
  и создаёт подтверждение проверки с отказом при нарушении условий.
- `agent-lifecycle research summary --package <путь> --validation <путь> --out <путь>`:
  создаёт ограниченную сводку с подтверждёнными утверждениями, пробелами,
  группами дубликатов и распределением статусов.

Команды исследования читают только явно переданные локальные пути. Они не
загружают URL, не обращаются к моделям и не запускают внешние процессы. Сводка
является входом для планирования, а не спецификацией, зафиксированным планом
или решением о приёмке. См. [проверку исследовательских материалов](research-evidence.md)
и [рабочий процесс исследования](../guides/research-workflow.md).

## Адаптеры

Для обычного запуска используйте `agent-lifecycle start`. Следующие команды
остаются отдельным интерфейсом для сценариев автоматизации и опытных
пользователей.

- `agent-lifecycle adapter validate`: проверка дескриптора.
- `agent-lifecycle adapter inspect`: безопасный осмотр адаптера.
- `agent-lifecycle adapter plugin-qualify --adapter codex|claude|cursor
  --profile <путь> --package <путь> --project-root <путь>`: явная ограниченная
  проверка обнаружения Agent Plugins в клиенте и создание квалификационной
  квитанции. Установка остаётся ответственностью клиента; статус `QUALIFIED`
  не доказывает выполнение жизненного цикла или управляемый запуск.
- `agent-lifecycle adapter install-plan`: пробный план установки без записи.
- `agent-lifecycle adapter event-check`: проверка нейтрального потока событий
  адаптера.
- `agent-lifecycle adapter event-capture-check`: проверка объявленного
  `adapter-owned` захвата событий через дескриптор, манифест возможностей,
  поток событий и `agent-adapter-event-stream-receipt.v1`.
- `agent-lifecycle adapter thread-capability --descriptor <путь> --manifest
  <путь> [--receipt <путь>]`: проверяет объявленные операции тредов выбранного
  адаптера и возвращает их эффективные статусы без обращения к хосту.
- `agent-lifecycle adapter thread-qualify --descriptor <путь> --receipt
  <путь> [--manifest <путь>]`: проверяет квалификационную квитанцию адаптера по
  отпечаткам дескриптора и capability-manifest. При неверном объявлении,
  квитанции или связи команда завершается с ненулевым кодом.
- `agent-lifecycle adapter session start/status/resume/promote`: запись и
  возобновление сессий адаптеров. Обычная интерактивная сессия возвращает
  `WAITING_FOR_TASK`; повышенная сессия связывается с состоянием рабочего цикла
  и задачей.
- `agent-lifecycle adapter launch-profile --adapter codex|claude|opencode
  --repository-root <каталог ALK> --out .alk/host-launch/<adapter>.json`:
  создаёт локальный профиль с точной привязкой к версии, не запуская внешний
  инструмент. Затем выполните `host-launch preflight`; см.
  [запуск зафиксированной задачи через проверенный
  профиль](qualified-host-launch.md).
  В том же файле есть раздел кандидата для планирования, но проверка версии
  сама по себе не подтверждает готовность маршрута планирования.
- `agent-lifecycle adapter session start --launch`: проверяет запрошенный
  профиль запуска и затем возвращает `adapter-generic-launch-disabled` до
  создания процесса. Один дескриптор не является полномочием на общий прямой
  запуск CLI хоста. Общий выбор окружения принимает только точные имена из
  разрешённого списка, а шаблоны отклоняются.
- `agent-lifecycle start --mode implement --launch --host-launch-profile
  <путь>`: единственный маршрут командной строки для локального запуска
  внешнего процесса. Требует зафиксированный запуск с файлом блокировки и
  выведенный профиль риска; публичный статус адаптера остаётся `WRAPPER_ONLY`.
- `agent-lifecycle adapter task start --adapter <id> (--file task.md |
  --text "...")`: принимает задачу для выбранного адаптера. Обычный текст и
  Markdown возвращают `agent-adapter-task-start-receipt.v1` со статусом
  `REVIEW_REQUIRED`; `--task-file` и `--task-text` являются псевдонимами. В
  подтверждении может быть рекомендательное поле `reviewMeshRecommendation`,
  если дополнительные проверяющие могут помочь, но вход остаётся черновым.
  Структурированный `agent-adapter-task-run-request.v1` или зафиксированный
  манифест с `--state`, `--lock`, `--task`, `--operation-id`,
  `--expected-revision` и `--source-revision` передаются в управляемый запуск.
- `agent-lifecycle adapter run`: связывает сессию адаптера с зафиксированным
  состоянием рабочего цикла и возвращает управляемый следующий шаг ALK. Для
  этого управляемого пути прогресс по умолчанию показывается в stderr, а JSON stdout
  остаётся `agent-adapter-session-receipt.v1`. Команда не обходит общий запрет
  запуска и не создаёт процесс CLI хоста.

## Контекст и продолжение

- `agent-lifecycle context check/render`: проверка и подготовка компактного
  контекста.
- `agent-lifecycle context external-import`: импорт одного локального файла
  внешнего контекста как `agent-external-context-import-receipt.v1` без вызовов
  сети, модели или провайдера.
- `agent-lifecycle context episode-retrieve`: создание
  `agent-episode-retrieval.v1` по явно переданным артефактам и необязательным
  `--external-context` артефактам.
- `agent-lifecycle context checkpoint`: создание ограниченного
  `agent-context-checkpoint.v1` по явно переданным сессии, состоянию, плану и
  сводке.
- `agent-lifecycle context restore`: проверка происхождения и создание
  `agent-context-continuation.v1` после сжатия контекста. Устаревший или
  изменённый снимок блокируется и не даёт полномочий на реализацию.
- `agent-lifecycle goal`: проверка, краткий снимок, объединённое представление
  цели и прогресса, обновление записи цели. `goal view` читает запись цели,
  состояние рабочего цикла, необязательные подтверждения расхода и счётчик
  изменений без изменения состояния.
- `agent-lifecycle followup`: учёт продолжений, которые не должны потеряться.
- `agent-lifecycle evidence`: индекс подтверждающих артефактов.
- `agent-lifecycle report status-view/event-feed/multi-run/progress/change-summary`:
  представления без записи для статуса, событий, ограниченного внимания по
  нескольким запускам, прогресса жизненного цикла и счётчика изменений. Multi-run
  читает только явно указанные корни и сообщает о пересечениях без изменения
  полномочий. Прогресс поддерживает ограниченный режим `--watch` и явный
  текстовый вывод `--terminal`.
- `agent-lifecycle report progress-bridge`: создаёт
  `agent-progress-bridge-receipt.v1` для обёрток адаптеров, которым нужен
  стабильный JSON-артефакт и, при необходимости, текст для терминала.
- `agent-lifecycle-neutrality scan --scope tracked-release --policy <файл>`:
  проверяет содержимое выпуска, привязанное к индексу Git. Флаг
  `--include-local-artifacts` явно добавляет только корни из
  `localArtifactRoots`; старые области остаются допустимыми, но помечаются в
  подписи как устаревшие. Подробнее: [проверка нейтральности](neutrality.md).
