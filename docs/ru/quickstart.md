# Быстрый старт

Этот пример показывает минимальный полезный запуск из исходного дерева. Сначала
выполняются локальные проверки, затем выбирается явный маршрут адаптера для
работы с внешним инструментом.

Устройство проекта описано в [архитектуре системы](architecture/system-architecture.md).
Отличия от кодовых агентов, сред запуска, инструментов спецификации и систем
памяти описаны в [сравнении проекта](reference/project-comparison.md).
Полный порядок действий для исследования, планирования, проверки, реализации и
возобновления приведён в руководстве [Как ALK работает с разными
задачами](guides/how-alk-works.md).
Границы нескольких агентов, настройка рабочих потоков, выбор модели, промпты,
тайм-ауты и повторы описаны в разделе [Настройка рабочего процесса и управления
выполнением](reference/workflow-customization.md).

## Установка из исходников

```bash
python -m pip install -e .
agent-lifecycle version
```

Без установки можно запустить команду прямо из дерева:

```bash
PYTHONPATH=src python -m agent_lifecycle version
```

## Установка из пакета

Официальный [проект в PyPI](https://pypi.org/project/agent-lifecycle-kit/)
поддерживает Python 3.11-3.14. Если пакет опубликован для нужной версии,
устанавливайте точную семантическую версию:

```bash
python -m pip install agent-lifecycle-kit==1.62.0
agent-lifecycle version
```

Если нужная версия ещё не опубликована в PyPI, используйте установку из
исходного дерева выше.
Одного Git-тега недостаточно для установки плагина: манифесты плагина внутри
тега тоже должны содержать ту же версию. Подробнее:
[публикация плагинов](reference/plugin-publication.md).

## Проверка готовности

```bash
agent-lifecycle diagnose --no-install-plans
```

Отчёт не раскрывает локальные абсолютные пути и секреты. Команда проверяет
метаданные пакета, профили, дескрипторы адаптеров, безопасный осмотр и
публичные резюме подтверждений. Запуск внешнего инструмента выполняется через
отдельный маршрут адаптера.

Для одного адаптера:

```bash
agent-lifecycle diagnose \
  --adapter adapters/<adapter-id>/adapter.descriptor.json \
  --no-install-plans
```

## Пробный план установки адаптера

```bash
agent-lifecycle adapter install-plan \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json
```

Команда показывает проверенные данные дескриптора: файлы, argv-массивы и
действия оператора. После проверки примените перечисленные действия оператора
для настройки внешнего инструмента.

## Проверка плана

Для зафиксированного плана:

```bash
agent-lifecycle plan check \
  --manifest path/to/plan.manifest.json \
  --lock path/to/plan.lock.json
```

План остаётся источником правды для владельца, границ записи, критериев
приёмки, проверок и подтверждающих артефактов.

## Импорт файлов планирования

Чтобы проверить внешний файл планирования перед превращением в план ALK:

```bash
agent-lifecycle import plan \
  --source specs/checkout.md \
  --dialect openspec \
  --out work/imports/checkout-import.json
```

Чтобы проверить папку с несколькими Markdown-файлами:

```bash
agent-lifecycle import plan \
  --source specs/checkout/ \
  --dialect spec-kit \
  --out work/imports/checkout-folder-import.json
```

Эта же команда поддерживает `--dialect bmad` и `--dialect spec-kitty`.
Импортированный материал поступает на стадию черновика. Перед реализацией его
нужно проверить и заморозить как план ALK.

## Профиль рабочего процесса проекта

Чтобы задать для проекта адаптер и ограниченные настройки этапов по умолчанию,
создайте локальный профиль:

```bash
agent-lifecycle project profile init --adapter <adapter-id> --out .alk/project-profile.json
agent-lifecycle project profile check
```

Необязательный параметр `--adapter` записывает адаптер по умолчанию в профиль.
Если его не указывать, задайте `defaultAdapter` в локальном файле или передавайте
`--adapter` в каждой команде. После выбора адаптера в простой команде его можно
не указывать:

```bash
agent-lifecycle start --file task.md
agent-lifecycle start --text "Исследовать ошибку в кэше"
```

Профиль проекта задаёт только локальные значения по умолчанию. Зафиксированный
план и его lock-файл остаются источником полномочий для риска, качества,
границ записи и обязательных подтверждений. Формат файла, явный выбор профиля
и расширенный маршрут `--no-project-profile` описаны в разделе [Профиль рабочего
процесса проекта](reference/project-workflow-profile.md).

## Выбор способа работы с адаптером

Выберите `<adapter-id>` в [таблице адаптеров со
ссылками](adapters/usage-modes.md). Подробные границы работы нескольких агентов,
настройки этапов плана, модели, промптов, тайм-аутов и повторов приведены в
разделе [Настройка рабочего процесса и управления выполнением](reference/workflow-customization.md).
Есть два обычных способа начать работу:

- Во внешнем инструменте, для которого на странице адаптера описана установка
  модуля или общего навыка, откройте целевой проект и отправьте приведённый ниже
  запрос. Модель и инструменты запускает внешний инструмент.
- В терминале проекта выполните `agent-lifecycle start --adapter
  <adapter-id>`. ALK прочитает задачу и создаст подтверждение. Для одного
  связанного процесса хоста добавьте квалифицированный маршрут `--launch`.

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи задачу через полный цикл ALK: уточни требования, составь и независимо
проверь план, зафиксируй его до реализации, проверь результаты реализации и
заверши работу только после принятия подтверждений и итогового доказательства.
Задача: <опиши задачу или укажи Markdown-файл>
```

Такой запрос прямо требует полного процесса ALK, а не только общего следования
навыку. На странице конкретного адаптера указано, как внешний инструмент
загружает или вызывает навык. Для адаптера без встроенного маршрута используйте
команду в терминале.

Подключаемый модуль или навык передаёт внешнему инструменту правила работы ALK.
Полный цикл подтверждают переходы состояния ALK, проверки, аудиты и принятые
подтверждения. Способы установки и вызова для всех двенадцати встроенных адаптеров приведены в разделе
[использование ALK с адаптером](adapters/usage-modes.md).

## Единая команда запуска

Для файла задачи или короткого текста:

```bash
agent-lifecycle start --adapter <adapter-id> --file task.md
agent-lifecycle start --adapter <adapter-id> --text "Исправь падающий тест"
```

По умолчанию используется режим `auto`. Обычный текст создаёт
`agent-lifecycle-start-receipt.v1` с черновым результатом, который проходит
проверку. Для узкой цели укажите режим подготовки:

```bash
agent-lifecycle start --adapter <adapter-id> --mode research --file research.md
agent-lifecycle start --adapter <adapter-id> --mode plan --file feature.md
agent-lifecycle start --adapter <adapter-id> --mode review --file proposed-plan.md
```

Чтобы запросить один внешний процесс только для планирования, добавьте
`--launch`:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode plan \
  --file feature.md \
  --launch
```

Маршрут использует профиль точной версии со статусом
`PLANNING_ONLY_QUALIFIED`. Текущая матрица планирования показывает состояние
профиля каждого встроенного адаптера и команды подготовки квалификации. Подробнее:
[запуск адаптера только для планирования](reference/planning-only-launch.md).

Только явный режим `implement` может передать управление существующему
управляемому шагу. Для него нужен структурированный зафиксированный запрос с
полной привязкой состояния, манифеста, lock-файла, задачи, операции и ревизий:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode implement \
  --file work/run/adapter-run-request.json
```

Для зафиксированной задачи добавьте `--risk auto`, чтобы определить нейтральный
класс модели и ограничения ресурсов. Шаг чтения сохраняет точный профиль через
`--risk-profile-out`, после чего его нужно отдельно разрешить командой
`workflow task-start --risk-profile`. Полная последовательность приведена в
разделе [Запуск с учётом риска](reference/risk-aware-execution.md). Для обычного
текста или Markdown параметр `--risk` записывает рекомендацию; разрешение
реализации берётся из зафиксированной привязки рабочего цикла.

Артефакт запуска также содержит краткое поле `executionStrategy`. Для обычного
входа оно имеет состояние `DEFERRED_UNTIL_FREEZE`; для полностью связанной
зафиксированной задачи показывает нижнюю границу качества, нейтральный класс
модели, вид пакета, режим проверки и ограничения ресурсов. Опытный пользователь
может записать полный артефакт командой `strategy resolve` и передать его в
`task compile --strategy`. Подробнее: [стратегия выполнения без снижения
качества](reference/execution-strategy.md).

Чтобы возобновить обычную управляемую сессию, ранее записанную ALK:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --resume <session-id> \
  --session-root .alk/adapter-sessions
```

Команда проверяет сохранённый адаптер и происхождение состояния. Идентификатор
относится к управляемой ALK-сессии рабочего цикла. Для идентификатора, который
вернул запуск планирования, не указывайте `--session-root`:

```bash
agent-lifecycle start --adapter <adapter-id> --resume <planning-session-id>
```

Команда читает состояние с отпечатками из `.alk/planning-sessions`. Опытный
пользователь может создать и предварительно проверить описание точной версии для
любого встроенного адаптера; для принятого запуска используйте профили,
указанные для зафиксированной задачи.
Для квалифицированного адаптера подставьте точные идентификаторы и пути из
[руководства по квалифицированному запуску](reference/qualified-host-launch.md):

```bash
agent-lifecycle adapter launch-profile \
  --adapter <qualified-adapter-id> \
  --repository-root /path/to/agent-lifecycle-kit \
  --out .alk/host-launch/<qualified-adapter-id>.json
agent-lifecycle host-launch preflight \
  --profile .alk/host-launch/<qualified-adapter-id>.json
```

После этого одну локальную команду можно явно запустить только из
зафиксированного режима `implement` с профилем риска:

```bash
agent-lifecycle start \
  --adapter <qualified-adapter-id> \
  --mode implement \
  --file work/run/adapter-run-request.json \
  --risk auto \
  --host-model-profile <host-model-profile.json> \
  --launch \
  --host-launch-profile .alk/host-launch/<qualified-adapter-id>.json
```

Сначала создайте и проверьте исключённый из Git профиль. Его формат, проверка
готовности и условия безопасного отказа описаны в разделе [локальный запуск
внешней команды](reference/local-host-launch.md). Для автоматизации остаются
отдельные команды `adapter task start`, `adapter run` и `adapter session resume`
из [справочника команд](reference/cli.md).
Отдельный маршрут реализации зафиксированной задачи и ограничения приёмки
S1/S2 приведены в разделе [квалифицированный запуск внешнего
инструмента](reference/qualified-host-launch.md). Для планирования используется
описанный выше отдельный маршрут.

## Проверка изменений

Для локальной ветки, запроса на слияние в GitHub или запроса на слияние в
GitLab сначала подготовьте файл изменений и короткую задачу проверки:

```bash
mkdir -p work/code-review/current
git diff origin/main...HEAD > work/code-review/current/diff.patch
```

Затем передайте задачу в ALK без запуска реализации:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode review \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/start.json

agent-lifecycle review-mesh recommend \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/recommendation.json
```

Используйте этот путь для обычной проверки файла изменений, архитектурной проверки,
проверки безопасности и оценки риска перед слиянием. Подробные примеры для
GitHub, GitLab, архитектуры и аудита реализации:
[сценарии проверки кода](code-review-workflows.md).

## Дополнительная проверка несколькими моделями ИИ

Для исследования, планирования или сложного аудита один материал можно
независимо проверить в разных связках CLI и моделей, например в Codex, Claude
Code и OpenCode/GLM. Сначала получите локальную рекомендацию Review Mesh:

```bash
agent-lifecycle review-mesh recommend --file task.md
```

Чтобы подготовить локальные пакеты проверяющих из артефакта приёма задачи:

```bash
agent-lifecycle adapter task start \
  --adapter <adapter-id> \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/intake.json

agent-lifecycle review-mesh prepare \
  --intake work/code-review/current/intake.json \
  --template leader-draft-review \
  --reviewer reviewer-a:plan-reviewer:strong-reasoning \
  --reviewer reviewer-b:risk-reviewer:strong-reasoning \
  --reviewer reviewer-c:independent-reviewer:local-strong-review \
  --out-dir work/code-review/current/review-mesh \
  --out work/code-review/current/review-mesh-prepare.json
```

Выбранный CLI выполняет каждое подготовленное задание, после чего
структурированный ответ импортируется обратно. Если проверенный зафиксированный
план явно включает этот режим, используйте
`review-mesh prepare` или атомарные команды `assign`, `import-result`,
`synthesize` и `quorum`, чтобы координировать подтверждения проверяющих через
выбранные адаптеры.
Подробные примеры:
[проверка несколькими моделями ИИ](review-mesh-workflow.md).
Можно использовать любые доступные связки адаптеров и моделей. Review Mesh
необязателен и по умолчанию выключен. Если доступна только одна модель,
продолжайте обычную проверку одним рецензентом, если зафиксированный план явно
не требует кворума.
Сценарии, которые останавливаются на исследовании, плане, проверке Markdown или
аудите реализации: [практические сценарии жизненного цикла](lifecycle-cookbook.md).

## Компактный контекст

Перед передачей задачи небольшой модели проверьте профиль:

```bash
agent-lifecycle context check \
  --profile profiles/small-context-profile.v1.json
```

Профиль удерживает контекст коротким и явным, но не отключает обязательные
проверки качества.

## Просмотр цели и прогресса

Если для запуска уже есть запись цели и состояние рабочего цикла, используйте
одно представление без записи, чтобы увидеть ожидаемый результат, текущую фазу,
время, расход токенов и счётчик изменений:

```bash
agent-lifecycle goal view \
  --record work/run/goal.json \
  --state work/run/state.json \
  --usage-receipt work/run/usage.json \
  --change-summary work/run/change-summary.json \
  --terminal
```

Команда только читает существующие артефакты. Её можно запускать во втором
терминале, пока адаптер выполняет работу.

## Локальное сравнение изменений процесса

Встроенный детерминированный набор не требует учётной записи модели или
внешнего инструмента:

```bash
mkdir -p work
cp tests/benchmarks/fixtures/accepted-pass.json work/benchmark-submission.json
agent-lifecycle benchmark evaluate \
  --suite benchmarks/reference-tasks/manifest.json \
  --artifact work/benchmark-submission.json \
  --out work/benchmark-evaluation.json
```

Результат содержит итоги правил, ложные приёмки, повторы, время и группы
токенов с обозначенной достоверностью. Перед сравнением запусков прочитайте
[руководство по эталонным задачам](guides/reference-task-evaluation.md).

## Проверка нейтральности выпуска

Для переносимой проверки исходного дерева или выпуска используйте область,
привязанную к индексу Git:

```bash
agent-lifecycle-neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --require-zero-findings
```

Игнорируемые подтверждения из разрешённых политикой каталогов не читаются,
пока отдельный шаг не добавит `--include-local-artifacts`. Перед включением
прочитайте [справочник по проверке нейтральности](reference/neutrality.md).

## Что дальше

- [Установка адаптеров](adapters/install.md)
- [Сценарии проверки кода](code-review-workflows.md)
- [Практические сценарии жизненного цикла](lifecycle-cookbook.md)
- [Справочник команд](reference/cli.md)
- [Диагностика готовности](reference/readiness-diagnostics.md)
- [Проверка нейтральности](reference/neutrality.md)
