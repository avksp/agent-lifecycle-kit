# Быстрый старт

Этот пример показывает минимальный полезный запуск из исходного дерева. Он не
делает реальных вызовов модели и не меняет настройки локальной среды.

Устройство проекта описано в [архитектуре системы](architecture/system-architecture.md).
Отличия от кодовых агентов, сред запуска, инструментов спецификации и систем
памяти описаны в [сравнении проекта](reference/project-comparison.md).
Полный порядок действий для исследования, планирования, проверки, реализации и
возобновления приведён в руководстве [Как ALK работает с разными
задачами](guides/how-alk-works.md).

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
python -m pip install agent-lifecycle-kit==1.61.0
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
публичные резюме подтверждений. Реальные вызовы моделей не запускаются.

Для одного адаптера:

```bash
agent-lifecycle diagnose \
  --adapter adapters/codex/adapter.descriptor.json \
  --no-install-plans
```

## Пробный план установки адаптера

```bash
agent-lifecycle adapter install-plan \
  --descriptor adapters/opencode/adapter.descriptor.json
```

Команда показывает проверенные данные дескриптора: файлы, argv-массивы и
действия оператора. Она не выполняет эти массивы, не меняет настройки локальной
среды и не повышает зрелость адаптера.

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
Импортированный материал остаётся черновым кандидатом. Он не запускает
реализацию и не заменяет зафиксированный план ALK, пока не пройдёт проверку и
заморозку.

## Единая команда запуска

Для файла задачи или короткого текста:

```bash
agent-lifecycle start --adapter codex --file task.md
agent-lifecycle start --adapter codex --text "Исправь падающий тест"
```

По умолчанию используется режим `auto`. Обычный текст не запускает реализацию:
команда возвращает `agent-lifecycle-start-receipt.v1` с черновым результатом,
который должен пройти проверку. Для узкой цели укажите неисполняющий режим:

```bash
agent-lifecycle start --adapter codex --mode research --file research.md
agent-lifecycle start --adapter codex --mode plan --file feature.md
agent-lifecycle start --adapter codex --mode review --file proposed-plan.md
```

Чтобы запросить один внешний процесс только для планирования, добавьте
`--launch`:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode plan \
  --file feature.md \
  --launch
```

Маршрут доступен только для точной версии с состоянием
`PLANNING_ONLY_QUALIFIED`. Поставляемые профили Codex, Claude Code и OpenCode
пока остаются кандидатами с безопасным отказом, а остальные встроенные
адаптеры этот маршрут ещё не объявляют. Заблокированное подтверждение содержит
команды подготовки, но не разрешает обходить квалификацию. Подробнее: [запуск
адаптера только для планирования](reference/planning-only-launch.md).

Только явный режим `implement` может передать управление существующему
управляемому шагу. Для него нужен структурированный зафиксированный запрос с
полной привязкой состояния, манифеста, lock-файла, задачи, операции и ревизий:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode implement \
  --file work/run/adapter-run-request.json
```

Для зафиксированной задачи добавьте `--risk auto`, чтобы определить нейтральный
класс модели и ограничения ресурсов. Шаг чтения сохраняет точный профиль через
`--risk-profile-out`, после чего его нужно отдельно разрешить командой
`workflow task-start --risk-profile`. Полная последовательность приведена в
разделе [Запуск с учётом риска](reference/risk-aware-execution.md). Для обычного
текста или Markdown параметр `--risk` остаётся рекомендацией и не разрешает
реализацию.

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
  --adapter codex \
  --resume <session-id> \
  --session-root .alk/adapter-sessions
```

Команда проверяет сохранённый адаптер и происхождение состояния. Значение
`--resume` не трактуется как идентификатор диалога Codex, Claude, OpenCode или
другого внешнего инструмента. Для идентификатора, который вернул запуск
планирования, не указывайте `--session-root`:

```bash
agent-lifecycle start --adapter codex --resume <planning-session-id>
```

Команда читает состояние с отпечатками из `.alk/planning-sessions` и не
перезапускает внешний CLI. По умолчанию внешний процесс не запускается.
Опытный пользователь сначала может создать и проверить профиль с точной
привязкой к версии Codex, Claude Code или OpenCode:

```bash
agent-lifecycle adapter launch-profile \
  --adapter codex \
  --repository-root /path/to/agent-lifecycle-kit \
  --out .alk/host-launch/codex.json
agent-lifecycle host-launch preflight \
  --profile .alk/host-launch/codex.json
```

После этого одну локальную команду можно явно запустить только из
зафиксированного режима `implement` с профилем риска:

```bash
agent-lifecycle start \
  --adapter codex \
  --mode implement \
  --file work/run/adapter-run-request.json \
  --risk auto \
  --host-model-profile profiles/hosts/codex-live-profile.v1.json \
  --launch \
  --host-launch-profile .alk/host-launch/codex.json
```

Сначала создайте и проверьте исключённый из Git профиль. Его формат, проверка
готовности и условия безопасного отказа описаны в разделе [локальный запуск
внешней команды](reference/local-host-launch.md). Для автоматизации остаются
отдельные команды `adapter task start`, `adapter run` и `adapter session resume`
из [справочника команд](reference/cli.md).
Отдельный маршрут реализации зафиксированной задачи и ограничения приёмки
S1/S2 приведены в разделе [квалифицированный запуск внешнего
инструмента](reference/qualified-host-launch.md). Его нельзя считать
подтверждением запуска для планирования.

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
  --adapter codex \
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
  --adapter codex \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/intake.json

agent-lifecycle review-mesh prepare \
  --intake work/code-review/current/intake.json \
  --template leader-draft-review \
  --reviewer codex-example:plan-reviewer:strong-reasoning \
  --reviewer claude-example:risk-reviewer:strong-reasoning \
  --reviewer opencode-glm-example:independent-reviewer:local-strong-review \
  --out-dir work/code-review/current/review-mesh \
  --out work/code-review/current/review-mesh-prepare.json
```

ALK не выбирает и не запускает эти модели. Каждое подготовленное задание нужно
передать выбранному CLI, после чего структурированный ответ импортируется
обратно. Если проверенный зафиксированный план явно включает этот режим, используйте
`review-mesh prepare` или атомарные команды `assign`, `import-result`,
`synthesize` и `quorum`, чтобы координировать подтверждения проверяющих без
запуска хостов из ядра ALK.
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
