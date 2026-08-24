# Справочник команд

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
python -m pip install agent-lifecycle-kit==1.82.0
```

## Контракты ошибок и ресурсов

Корневой CLI возвращает `agent-lifecycle-error.v1` с кодом выхода `2` для
ожидаемых ошибок ввода-вывода, декодирования, глубины JSON и непредвиденных
ошибок. JSON очищается и не содержит трассировку или локальный абсолютный путь.
Поведение библиотечных исключений и `KeyboardInterrupt`/`SystemExit` не
меняется. См. [контракт ошибок CLI](cli-errors.md).

Встроенные профили загружаются через `importlib.resources`, поэтому команды
работают из установленного wheel вне исходного дерева. Одноимённый файл в
текущей папке не может подменить встроенный профиль, а явно переданный путь
сохраняет приоритет. Поддерживаемая поверхность импорта перечислена в
[справочнике API Python](python-api.md).

## Производительность и подтверждения ресурсов

В релизе 1.78 команда `version` быстрее запускается благодаря ленивой загрузке
групп команд. Измерительный контур и жёсткие пределы описаны в разделе
[бюджеты производительности и ресурсов](performance-and-resource-budgets.md).
Время является справочным, если план не установил иное; проверки безопасности,
совместимости, ресурсов и отказа по умолчанию остаются обязательными.

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
- `agent-lifecycle plan verify`: формирует безопасный отчёт проверки пакета
  плана: манифеста, трассируемости, lock-файла и целостности пакета. Команда не
  выполняет команды из плана и не даёт полномочий на изменения.
- `agent-lifecycle plan completeness-check`: возвращает
  `agent-plan-completeness-validation.v1` с конкретными блокерами по выбранному
  уровню.
- `agent-lifecycle plan acceptance-check`: проверка трассируемости критериев
  приёмки.
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
- `agent-lifecycle workflow init --state <путь> --run-id <id> --package-id
  <id>`: создаёт один приватный несвязанный файл
  `agent-workflow-state.v4` и не заменяет существующее состояние.
- `agent-lifecycle workflow state-migrate --state <путь> --operation-id <id>
  --expected-revision <n> --source-revision <sha>`: выполняет одну явную
  миграцию v3 в v4 с отказом при любой неоднозначности.
- `agent-lifecycle workflow task-start`: открывает ограниченную попытку задачи.
- `agent-lifecycle workflow task-snapshot`: без изменения состояния вычисляет
  текущий набор файлов задачи и отпечатки их содержимого по Git. Объект `claim`
  из результата нужно поместить в результат задачи перед `task-result`.
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
- `agent-lifecycle workflow`: остальные переходы жизненного цикла, отчёты задач и
  финальное подтверждение. Для запусков с обязательной проверкой причинной
  цепочки `workflow finalize` принимает
  `--proof-integrity <proof-integrity.json>`; для обязательного решения
  завершения принимает `--completion-gate-receipt <completion-gate.json>`.
  Если план требует аудит реализации, `workflow task-accept` принимает
  `--implementation-audit <implementation-audit.json>`, а `workflow finalize`
  принимает `--final-implementation-audit <final-implementation-audit.json>`.
  Для плана с обязательной групповой проверкой на финальном аудите
  `workflow finalize` принимает `--review-mesh-quorum <path>`.
- Управляемый вывод прогресса поддерживают только `workflow run`,
  `workflow task-result`, `workflow task-accept`, `workflow task-review-apply`
  и `workflow finalize`.
  `ALK_PROGRESS_HOOK=stderr` можно использовать в обёртках; установка плагина
  сама по себе не доказывает полный жизненный цикл.
- `agent-lifecycle runner`: управляемое выполнение с ограничениями ресурсов.
- `agent-lifecycle strategy resolve --manifest ... --lock ... --state ...
  --task ... --operation-id ... --expected-revision ... --source-revision ...
  --adapter ... --out ...`: записывает одну нейтральную стратегию выполнения
  без изменения состояния. Для S1/S2 нужен подходящий `--host-model-profile`.
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
- `agent-lifecycle audit`: проверка плана, реализации и вердиктов.
- `agent-lifecycle audit implementation`: структурированный отчёт
  `agent-implementation-audit-report.v1` по результату задачи и независимой
  проверке. Если зафиксированный план требует групповую проверку для аудита
  реализации, используйте `--review-mesh-quorum <path>`.
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
- `agent-lifecycle metrics audit-proposal --report <путь> --out <путь>`:
  фиксирует решение оператора по рекомендации. Флаг `--approved` следует
  использовать только после просмотра отчёта; замороженный план не меняется.
- `agent-lifecycle metrics audit-apply --proposal <путь> --out <путь>`:
  создаёт новый подтверждённый профильный артефакт. Манифест и lock-файл
  нельзя использовать как путь вывода.

Полный порядок сбора подтверждений, проверки на эталонных задачах и
подтверждения решения описан в разделе [оптимизация проверок по подтверждённым
данным](audit-optimization.md).
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
- `agent-lifecycle report status-view/event-feed/progress/change-summary`:
  представления без записи для статуса, событий рабочего цикла, прогресса
  жизненного цикла и счётчика изменений. Прогресс поддерживает ограниченный
  режим `--watch` и явный текстовый вывод `--terminal`.
- `agent-lifecycle report progress-bridge`: создаёт
  `agent-progress-bridge-receipt.v1` для обёрток адаптеров, которым нужен
  стабильный JSON-артефакт и, при необходимости, текст для терминала.
- `agent-lifecycle-neutrality scan --scope tracked-release --policy <файл>`:
  проверяет содержимое выпуска, привязанное к индексу Git. Флаг
  `--include-local-artifacts` явно добавляет только корни из
  `localArtifactRoots`; старые области остаются допустимыми, но помечаются в
  подписи как устаревшие. Подробнее: [проверка нейтральности](neutrality.md).
