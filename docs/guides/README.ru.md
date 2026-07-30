# Agent Lifecycle Kit

[English version](../../README.md)

Agent Lifecycle Kit — независимый от провайдера набор для управления полным
жизненным циклом агентной разработки: от исходной задачи и проверенной
SDD-спецификации до зафиксированного плана, контролируемой реализации,
независимой проверки и воспроизводимого финального вердикта.

Набор распространяется как один репозиторий с единым семантическим ядром и
нативными проекциями для Codex, Claude Code, Cursor, Gemini CLI, Hermes,
Kimi Code, OpenCode и qwen-code.

## Зачем он нужен

Агентная разработка ломается, когда план, бюджет выполнения, изменения,
проверки и финальное доказательство остаются только в истории чата. Agent
Lifecycle Kit превращает эти шаги в явные артефакты и контрольные проверки,
чтобы задачу можно было довести до проверяемого завершения без потери качества
и контроля ресурсов.

Используйте его, когда нужны:

- проверенное SDD-планирование до старта реализации;
- зафиксированные пакеты задач с ограниченными зонами ответственности и
  контрактами проверки;
- контролируемое выполнение с ограничениями контекста, бюджета и внешних
  действий;
- независимая проверка реализации перед приёмкой;
- доказательства по конкретной среде вместо широких неподтверждённых заявлений.

## Что делает набор

Полный жизненный цикл выглядит так:

```text
задача
  -> уточнения при необходимости
  -> SDD-спецификация
  -> независимая проверка и улучшение спецификации
  -> готовый к реализации план для агентов
  -> независимая проверка и улучшение плана
  -> неизменяемая фиксация
  -> компиляция пакетов задач
  -> авторизованная реализация
  -> проверка контроллером и независимая проверка каждой задачи
  -> исправление или изменение контракта при необходимости
  -> финальный аудит, терминальная проверка и воспроизводимое доказательство завершения
```

Жизненный цикл содержит пять канонических skills:

- `agent-first-planning`
- `audit-agent-plan`
- `agent-plan-to-workers`
- `agent-workflow-orchestrator`
- `audit-plan-implementation`

Skills остаются тонкими точками входа. Спецификациями, планами, lock-файлами,
пакетами задач, состоянием запуска, доказательствами, бюджетами и правилами
аудита управляет общее детерминированное ядро, а не отдельная реализация в
каждом адаптере.

## Режим компактного контекста

Системы с маленьким контекстным окном поддерживаются через детерминированный
профиль контекста, а не через свободное сокращение запроса. В поставке есть
`profiles/small-context-profile.v1.json`: он описывает окна 4k-strict, 8k,
16k, 32k и 64k, резервирует место под ответ, ограничивает активный пакет и
краткое состояние процесса, ограничивает сводки доказательств и вывода
инструментов, а также число последних дословных сообщений пользователя.
Тихое обрезание запрещено.

Если подготовленный пакет не помещается, контроллер должен разделить задачу,
запросить большее окно контекста или заблокировать запуск. Старый контекст и
вывод инструментов представляются хешируемыми сводками и идентификаторами
доказательств.

В наборе проверок совместимости есть отдельный сценарий `4k-strict`
(`S1-SMALL-CONTEXT-4K-STRICT-01`) поверх базового 8k-сценария, поэтому
поддержка локальных моделей с контекстом меньше 8k проверяется отдельным
контрактным путём.

## Калибровка расхода

Синтетический повтор полезен для детерминированных проверок регрессий, но не
является доказательством готовности к продвижению. Для продвижения нужны
отдельные реальные квитанции для совместимости жизненного цикла и калибровки
расхода.

```bash
python tools/release/validate_live_host_conformance.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --baseline conformance/core/adapter-baseline.v1.json \
  --receipt-dir <live-host-receipts-dir> \
  --promoted-hosts codex \
  --evidence <live-host-conformance-evidence.json>
```

Реальная квитанция с подтверждённым расходом проверяется по
`conformance/core/live-calibration-profile.v1.json` и
`conformance/core/budget-targets.v1.json`.

```bash
python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt-dir <live-calibration-receipts-dir> \
  --promoted-hosts codex \
  --evidence <live-calibration-evidence.json>
```

Валидатор отклоняет синтетические квитанции, отсутствие подтверждения расхода,
неподдерживаемые среды, неполное покрытие обязательных сценариев для этой
среды, падение качества и превышение p95-бюджета. Для общего заявления
`VERIFIED` нужна отдельная успешная квитанция совместимости и отдельная
успешная квитанция калибровки расхода по каждой среде из профиля.
Подробнее:
[live cost calibration](../reference/live-cost-calibration.md).

## Маршрутизация моделей

Маршрутизация моделей — детерминированная возможность ядра, не привязанная к
провайдеру. Ядро выбирает нейтральный класс модели для фазы жизненного цикла
или попытки выполнить задачу, а адаптер сопоставляет этот класс с конкретной
моделью провайдера или локальной среды выполнения вне переносимых артефактов.
Если у попытки есть
`attemptModelRoute.requiresUsageReceipt=true`, `workflow task-result`
завершается отказом до получения валидной квитанции расхода от среды.

```bash
agent-lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
agent-lifecycle model route --profile profiles/model-routing-profile.v1.json --request <model-route-request.json>
agent-lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
```

Переносимые классы: `no-model`, `budget`, `local-compact`, `standard-code`,
`local-standard-code`, `strong-reasoning`, `local-strong-review` и
`specialist-review`. Режим только с локальными моделями поддерживается, но
финальный аудит, проверка безопасности, проверка производительности,
продвижение и независимая проверка S2 требуют явно откалиброванный локальный
класс для сильной проверки, например `local-strong-review`. `local-compact` не
может тихо закрывать эти контрольные проверки.

Подробнее: [маршрутизация моделей](../reference/model-routing.md).

## Решения по бюджету

Бюджетные лимиты — это предохранители, а не критерий успешности задачи. Если
попытка с моделью превышает утверждённый лимит, процесс переходит в
`WAITING_FOR_BUDGET_DECISION`, а не принимает задачу. В manual mode оператор
решает, продолжать ли тот же маршрут, переключиться, разделить и заново
зафиксировать задачу или остановить выполнение. В auto mode политика может
переключать маршрут ограниченное число раз, но критические фазы проверки не
могут тихо перейти на более слабые классы.

После паузы оператор применяет решение отдельным вызовом той же команды
`workflow budget-decision` с `--action`. Этот шаг пишет неизменяемую квитанцию
применения и возвращает задачу в `RUNNING` или `READY`, либо оставляет процесс
заблокированным для `split-task`/`abort`.

Режимы бюджета:

- `metered`: нужен утверждённый лимит в USD.
- `subscription`: нужны `maxInvocations` и лимит токенов или времени.
- `local`: использует то же правило ресурсных лимитов, что и `subscription`.

Подробнее: [политика переключения по бюджету](budget-reroute-policy.md).

## Структура поставки

Универсальная поставка не означает единый формат манифеста. Текущий
тегированный исходный релиз содержит заявления поддержки и ссылки на
доказательства, перечисленные ниже. Одно детерминированное ядро проецируется в
родную модель загрузки каждой системы:

| Система | Артефакт релиза | Зрелость | Причина |
| --- | --- | --- | --- |
| Codex | `.codex-plugin/plugin.json` и `.agents/plugins/marketplace.json` | `VERIFIED` для Codex CLI 0.145.0 | Локально прошли реальная проверка совместимости release-0-6, калибровка расхода и полный жизненный цикл ALK. Одобрение публичного Plugins Directory не заявлено. |
| Claude Code | `.claude-plugin/plugin.json` и `.claude-plugin/marketplace.json` | `VERIFIED` для Claude Code 2.1.220 | Локально прошли реальная проверка совместимости release-0-5, калибровка расхода и полный жизненный цикл ALK. Одобрение публичного каталога не заявлено. |
| Cursor | `.cursor-plugin/plugin.json`, `.cursor-plugin/marketplace.json` и `adapters/cursor/*` | `EXPERIMENTAL` | Безопасная проверка прошла на локальной бесплатной подписке, но подтверждение расхода и полный жизненный цикл ещё не приняты. Одобрение Marketplace не заявлено. |
| Gemini CLI | `adapters/gemini-cli/*` | `EXPERIMENTAL` | Безопасная проверка и форма ограниченного запуска прошли, но локальная живая проверка заблокирована неподдерживаемым уровнем Gemini Code Assist. |
| Hermes | `skills.sh.json`, общий `skills/` и `adapters/hermes/*` | `VERIFIED` для Hermes Agent v0.19.0 | Локально прошли реальная совместимость, калибровка расхода и полный жизненный цикл ALK 2026-07-29. Одобрение публичного каталога или публикация не заявлены. |
| Kimi Code | `adapters/kimi-code/*` | `EXPERIMENTAL` | Безопасная проверка и форма ограниченного запуска прошли, но локальная живая проверка заблокирована до настройки provider/model alias. |
| OpenCode | `opencode.json`, общий `skills/` и `adapters/opencode/*` | `VERIFIED` для OpenCode CLI 1.18.9 | Локально прошли реальная совместимость, калибровка расхода и полный жизненный цикл ALK 2026-07-29. Публикация в npm не заявлена. |
| qwen-code | `adapters/qwen-code/*` | `VERIFIED` для qwen-code 0.21.0 | Локально прошли реальная совместимость, калибровка расхода и полный жизненный цикл ALK на GLM 5.2 2026-07-29. Одобрение публичного пакета не заявлено. |

`EXPERIMENTAL` означает, что у адаптера есть исходные метаданные, манифест
возможностей и офлайн-проверки совместимости, но это не заявление о готовой
живой совместимости. Адаптер получает `VERIFIED` только после ограниченной
живой проверки среды, калибровки расхода и полного доказанного жизненного цикла
для точной версии этой среды. Одна короткая проверка модели для этого
недостаточна.

Корень репозитория — канонический корень плагина для Codex, Claude Code и
Cursor. Каталоги `adapters/<host>/` остаются офлайн-проекциями совместимости и
метаданными конкретных сред. Пользователям следует устанавливать корневой
пакет, если будущий релиз явно не опубликует отдельный пакет адаптера.

## Установка и публикация

В примерах `vX.Y.Z` означает доверенный тег GitHub Release.

### Ядро из исходного кода

Для локальной разработки текущего репозитория:

```bash
python -m pip install -e .
agent-lifecycle version
agent-lifecycle diagnose
agent-lifecycle schema list
agent-lifecycle workflow status --state <path-to-run.state.json>
agent-lifecycle workflow next --state <path-to-run.state.json>
agent-lifecycle workflow task-start --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --reason "<reason>"
agent-lifecycle workflow task-result --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --result <task-result.json> --model-usage-receipt <model-usage-receipt.json> --reason "<reason>"
agent-lifecycle workflow task-accept --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --review <task-review.json> --reason "<reason>"
agent-lifecycle workflow finalize --state <path-to-run.state.json> --operation-id <id> --expected-revision <n> --source-revision <sha> --final-audit <final-audit.json> --proof <final-proof.json> --reason "<reason>"
agent-lifecycle audit ownership --manifest <plan.manifest.json> --base <base-ref> --fail-on-unowned --fail-on-forbidden
agent-lifecycle tier resolve --request <tier-request.json>
agent-lifecycle specification check --specification <specification.json>
agent-lifecycle plan check --manifest <plan.manifest.json> --lock <plan.lock.json>
agent-lifecycle task compile --manifest <plan.manifest.json> --out-dir <task-packet-dir> --write
agent-lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
agent-lifecycle model route --profile profiles/model-routing-profile.v1.json --request <model-route-request.json>
agent-lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
agent-lifecycle context profile-check --profile profiles/small-context-profile.v1.json
agent-lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 4k-strict
agent-lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
agent-lifecycle context render --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
agent-lifecycle adapter validate --descriptor adapters/codex/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/opencode/adapter.descriptor.json --skip-host-commands
agent-lifecycle adapter install-plan --descriptor adapters/opencode/adapter.descriptor.json
agent-lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
agent-lifecycle adapter scaffold --host synthetic-host --target /tmp/agent-lifecycle-adapter-scaffold --dry-run
agent-lifecycle-neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

Те же команды можно запускать без установки из рабочего дерева:

```bash
PYTHONPATH=src python -m agent_lifecycle version
PYTHONPATH=src python -m agent_lifecycle diagnose
PYTHONPATH=src python -m agent_lifecycle schema list
PYTHONPATH=src python -m agent_lifecycle workflow status --state <path-to-run.state.json>
PYTHONPATH=src python -m agent_lifecycle workflow next --state <path-to-run.state.json>
PYTHONPATH=src python -m agent_lifecycle workflow task-start --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle workflow finalize --state <path-to-run.state.json> --operation-id <id> --expected-revision <n> --source-revision <sha> --final-audit <final-audit.json> --proof <final-proof.json> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle audit ownership --manifest <plan.manifest.json> --base <base-ref> --fail-on-unowned --fail-on-forbidden
PYTHONPATH=src python -m agent_lifecycle tier resolve --request <tier-request.json>
PYTHONPATH=src python -m agent_lifecycle specification check --specification <specification.json>
PYTHONPATH=src python -m agent_lifecycle plan check --manifest <plan.manifest.json> --lock <plan.lock.json>
PYTHONPATH=src python -m agent_lifecycle task compile --manifest <plan.manifest.json> --out-dir <task-packet-dir> --write
PYTHONPATH=src python -m agent_lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
PYTHONPATH=src python -m agent_lifecycle model route --profile profiles/model-routing-profile.v1.json --request <model-route-request.json>
PYTHONPATH=src python -m agent_lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
PYTHONPATH=src python -m agent_lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
PYTHONPATH=src python -m agent_lifecycle adapter validate --descriptor adapters/codex/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
PYTHONPATH=src python -m agent_lifecycle adapter inspect --descriptor adapters/opencode/adapter.descriptor.json --skip-host-commands
PYTHONPATH=src python -m agent_lifecycle adapter install-plan --descriptor adapters/opencode/adapter.descriptor.json
PYTHONPATH=src python -m agent_lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>
PYTHONPATH=src python -m agent_lifecycle adapter scaffold --host synthetic-host --target /tmp/agent-lifecycle-adapter-scaffold --dry-run
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

Сейчас реализованы группы команд `version`, `diagnose`, `schema`, `workflow status`,
`workflow next`, `workflow block`, `workflow resolve`, `workflow task-start`,
`workflow task-result`, `workflow task-accept`, `workflow finalize`,
`audit ownership`, `tier resolve`, `context profile-check`, `context check`,
`context render`, `model profile-check`, `model route`, `model usage-check`,
`specification check`, `plan check`, `task compile`, `adapter validate`,
`adapter inspect`, `adapter install-plan`, `adapter event-check`, `adapter scaffold` и `neutrality`.
`adapter scaffold` — только заготовка и может создавать только
`EXPERIMENTAL`-проекции. `adapter inspect` записывает дескриптор и безопасно
обнаруживает возможности среды без запуска модели. Выполнение адаптера и
группы команд живой совместимости пока зарезервированы и завершаются отказом
со стабильным `agent-lifecycle-error.v1`.

`diagnose` собирает один сокращённый `agent-readiness-report.v1` по рабочему
дереву, метаданным пакета, профилям, адаптерам и доступности доказательств. По
умолчанию команда только читает состояние, включает сухие планы установки и не
меняет метки зрелости адаптеров.

`context check` и `context render` тоже завершаются отказом при переполнении:
если подготовленная квитанция получает `status: FAIL`, CLI завершается с
ненулевым кодом и возвращает `agent-lifecycle-error.v1` с кодом
`context-overflow`. Квитанция проверяет подготовленный пакет, резерв ответа,
активный пакет задачи, краткое состояние, сводку принятых доказательств,
необязательные `toolOutputs` и число последних дословных сообщений
пользователя.

`workflow finalize` требует `--final-audit`. Финальная проверка должна пройти с
`READY_FOR_FINALIZATION`, совпадать с `planRevision` и `planDigest` запуска,
не заявлять продвижение в эксплуатацию, не содержать нерешённых находок уровня
MEDIUM и выше и иметь корректный `agent-completion-signal.v1`. Если принятая
спецификация объявляет `completionCheck`, завершение дополнительно требует
квитанцию `agent-completion-check-receipt.v1`, связанную с тем же запуском,
отпечатком плана, исходной ревизией, доказательствами и проверяющим.

Действия, которые должен выполнить человек, фиксируются состоянием процесса, а
не текстовым обещанием о завершении. Запуск можно поставить в
`WAITING_FOR_EXTERNAL_ACTION` и продолжить только после подходящей квитанции
`agent-external-action-receipt.v1`. Проверка завершения для человеческого
решения должна ссылаться на эту квитанцию, а не создавать отдельный путь
одобрения.

Переходы процесса принудительно проверяют `controllerGates` задачи для фаз
`pre-launch`, `post-attempt`, `pre-acceptance` и `finalization`. Ожидаемые
квитанции вычисляются из зафиксированного шаблона `receiptPath` и должны
связывать контрольную проверку, запуск, пакет, задачу, попытку, фазу, операцию,
отпечаток плана, исходную ревизию, вердикт PASS, свежесть, зависимости и
настроенные поля подтверждения.

Тесты используют только стандартную библиотеку Python:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
```

### Codex

Установка из тегированного исходного marketplace:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref vX.Y.Z
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
```

Настроенные marketplace также доступны через `/plugins`. После установки
нужно начать новую сессию Codex, чтобы загрузились поставляемые skills.

Для публикации в публичный OpenAI Plugins Directory нужно отправить корневой
пакет как plugin только со skills через OpenAI plugin submission portal. Codex CLI
имеет `VERIFIED` только для проверенной версии 0.145.0 в текущем исходном
дереве; не заявляйте одобрение публичного каталога или более широкую поддержку
Codex, пока нет внешней проверки и соответствующих доказательств.

### Claude Code

Добавить marketplace и установить плагин:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

В интерактивной сессии Claude Code эквивалентная последовательность команд:

```text
/plugin marketplace add avksp/agent-lifecycle-kit
/plugin install agent-lifecycle-kit@agent-lifecycle-kit
/reload-plugins
```

Skills плагина используют пространство имён плагина, например
`/agent-lifecycle-kit:agent-workflow-orchestrator`.

Claude Code имеет `VERIFIED` только для проверенной версии 2.1.220 в текущем
исходном дереве. Заявление подтверждено реальной проверкой совместимости
release-0-5, калибровкой расхода и финальным доказательством полного жизненного
цикла ALK, перечисленными в матрице поддержки.

Для включения в публичный каталог Anthropic нужна внешняя проверка плагина.
Marketplace на уровне репозитория достаточно для частного распространения или
распространения в сообществе, но это не заявление об одобрении публичного
каталога.

### Cursor

Для локальной проверки перед отправкой скопируйте репозиторий или создайте
символическую ссылку в локальном каталоге плагинов Cursor:

```bash
mkdir -p ~/.cursor/plugins/local
ln -s /path/to/agent-lifecycle-kit ~/.cursor/plugins/local/agent-lifecycle-kit
```

Затем перезапустите Cursor или выполните `Developer: Reload Window`. После
локальной проверки отправьте публичный репозиторий на
`https://cursor.com/marketplace/publish`.

Для Teams/Enterprise импортируйте GitHub repo как team marketplace через
Dashboard -> Plugins. После публичного одобрения устанавливайте из Cursor
Marketplace или панели Customize. Если ваша сборка Cursor поддерживает
установку через чат:

```text
/add-plugin agent-lifecycle-kit
```

Проекция Cursor пока `EXPERIMENTAL`; локальная установка полезна для проверки,
но не для заявления о проверенной живой совместимости.

### Gemini CLI

Gemini CLI сейчас использует исходную проекцию для локальной среды. Установите
ядро из рабочего дерева, полученного по тегу, затем проверьте и
проинспектируйте проекцию:

```bash
git clone --branch vX.Y.Z https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python -m pip install -e .
gemini --version
agent-lifecycle adapter validate --descriptor adapters/gemini-cli/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/gemini-cli/adapter.descriptor.json
```

В текущем исходном дереве нет опубликованного пакета среды выполнения для
Gemini CLI. Исходное дерево содержит `adapters/gemini-cli/runner.py` и
`tools/live_hosts/gemini_cli_harness.py` для ограниченной нормализации
квитанций, но Gemini CLI остаётся `EXPERIMENTAL`, пока не приняты живые
квитанции совместимости, калибровка и доказательство полного жизненного цикла.
На текущей локальной среде Gemini CLI 0.46.0 возвращает ошибку
неподдерживаемого уровня Gemini Code Assist для individual-client, поэтому
продвижение невозможно без поддерживаемой настройки Gemini/Antigravity.

### Hermes

Hermes может устанавливать общие skills напрямую. Для установки всех skills
жизненного цикла из тегированного релиза:

```bash
for skill in agent-first-planning audit-agent-plan agent-plan-to-workers agent-workflow-orchestrator audit-plan-implementation; do
  hermes skills install "https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/vX.Y.Z/skills/${skill}/SKILL.md"
done
```

Корневой `skills.sh.json` содержит сведения для систем, которые читают индексы,
совместимые со skills.sh. `adapters/hermes/*` содержит экспериментальные
метаданные registry и slash-command. Это не заявление о живой проверке Hermes
plugin.

### Kimi Code

Kimi Code сейчас использует исходную проекцию для локальной среды. Убедитесь,
что CLI `kimi` доступен в `PATH`, затем проверьте и проинспектируйте проекцию:

```bash
git clone --branch vX.Y.Z https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python -m pip install -e .
kimi --version
agent-lifecycle adapter validate --descriptor adapters/kimi-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/kimi-code/adapter.descriptor.json
```

В текущем исходном дереве нет опубликованного пакета среды выполнения для Kimi
Code. Исходное дерево содержит `adapters/kimi-code/runner.py` и
`tools/live_hosts/kimi_code_harness.py` для ограниченной нормализации
квитанций, но Kimi Code остаётся `EXPERIMENTAL`, пока не приняты живые
квитанции совместимости, калибровка и доказательство полного жизненного цикла.
На текущей локальной среде `kimi provider list` показывает, что providers не
настроены, поэтому продвижение невозможно до настройки provider/model alias вне
переносимого ядра ALK.

### OpenCode

OpenCode загружает плагины и skills разными механизмами. Для установки в
проект скопируйте общие skills и адаптер в целевой проект:

```bash
KIT=/path/to/agent-lifecycle-kit
mkdir -p .opencode/skills .opencode/plugins
cp -R "$KIT"/skills/* .opencode/skills/
cp "$KIT"/adapters/opencode/plugins/agent-lifecycle-kit.js .opencode/plugins/
```

Для установки на уровне пользователя:

```bash
KIT=/path/to/agent-lifecycle-kit
mkdir -p ~/.config/opencode/skills ~/.config/opencode/plugins
cp -R "$KIT"/skills/* ~/.config/opencode/skills/
cp "$KIT"/adapters/opencode/plugins/agent-lifecycle-kit.js ~/.config/opencode/plugins/
```

В корне репозитория также есть `opencode.json` для проверки из рабочего дерева.
Будущий npm-пакет может ссылаться на тот же адаптер, но текущее исходное дерево
не заявляет публикацию в npm.

### qwen-code

qwen-code сейчас использует исходную проекцию для локальной среды. Установите
ядро из рабочего дерева, полученного по тегу, затем проверьте и
проинспектируйте проекцию. Текущее исходное дерево имеет `VERIFIED` для
qwen-code `0.21.0`.

```bash
git clone --branch vX.Y.Z https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python -m pip install -e .
qwen --version
agent-lifecycle adapter validate --descriptor adapters/qwen-code/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
agent-lifecycle adapter inspect --descriptor adapters/qwen-code/adapter.descriptor.json
```

Живой runner находится в `adapters/qwen-code/runner.py`, проверочный скрипт
релиза - в `tools/live_hosts/qwen_code_harness.py`. Для текущего исходного
дерева не заявлены публичный пакет адаптера qwen-code, одобрение публичного
каталога или прохождение производственной матрицы.

## Использование

Для полного жизненного цикла попросите систему запустить
`agent-workflow-orchestrator`:

```text
Используй skill agent-workflow-orchestrator.

Задача: <опиши требуемый результат>.

Задавай только блокирующие уточняющие вопросы. Построй готовый к реализации
SDD-план и независимо проверяй его до готовности к фиксации. Перед реализацией
запроси разрешение. Проверяй каждую выполненную задачу независимо от автора.
Перед сообщением о завершении проведи финальный аудит и терминальную проверку.
```

Если система поддерживает явный вызов:

- Codex: выберите Agent Lifecycle Kit или попросите Codex использовать
  `agent-workflow-orchestrator`
- Claude Code: `/agent-lifecycle-kit:agent-workflow-orchestrator`
- Cursor: попросите Agent использовать `agent-workflow-orchestrator`
- Gemini CLI: используйте исходную проекцию только для проверки, пока живая
  поддержка не повышена до `VERIFIED`
- Hermes: используйте `/agent-workflow-orchestrator` после установки skill;
  текущее дерево имеет `VERIFIED` для Hermes Agent v0.19.0
- Kimi Code: используйте исходную проекцию только для проверки, пока живая
  поддержка не повышена до `VERIFIED`
- OpenCode: попросите агента загрузить `agent-workflow-orchestrator` через
  нативный механизм skills; текущее дерево имеет `VERIFIED` для OpenCode CLI
  1.18.9
- qwen-code: используйте исходную проекцию с qwen-code `0.21.0`; текущее
  дерево имеет `VERIFIED` для живых квитанций GLM 5.2

Точный синтаксис с пространствами имён определяется матрицей поддержки
конкретного релиза. Экспериментальная проекция адаптера не является заявлением
о живой совместимости.

### Использование отдельных skills

Используйте `agent-first-planning`, когда нужны уточнения, SDD-спецификация и
готовый к реализации план без запуска реализации:

```text
Используй agent-first-planning, чтобы преобразовать задачу в независимо
проверяемый SDD-пакет плана. Остановись до начала реализации.
```

Используйте `audit-agent-plan` для независимой проверки черновика или заново
открытого плана. Находки должны идти первыми:

```text
Используй audit-agent-plan для проверки полной ревизии плана. Не реализуй и не
исправляй его скрытно; верни стабильные находки и вердикт готовности.
```

Используйте `agent-plan-to-workers` только после независимой проверки и
фиксации плана:

```text
Используй agent-plan-to-workers, чтобы скомпилировать зафиксированный план в
неизменяемые пакеты задач. Не меняй DAG и зоны ответственности.
```

Используйте `agent-workflow-orchestrator` для запуска или продолжения полного
авторизованного жизненного цикла:

```text
Используй agent-workflow-orchestrator, чтобы продолжить зафиксированный запуск
из сохранённого состояния, применить бюджеты и разрешения и провести каждую
задачу через проверку.
```

Используйте `audit-plan-implementation` для аудита без изменений: одной
попытки выполнить задачу или всей реализации.

```text
Используй audit-plan-implementation для аудита с находками в начале:
сопоставь зафиксированный план, пакет, изменённые файлы, тесты и
доказательства. Не исправляй находки.
```

## Выполнение и разрешения

Сохранённое состояние процесса не зависит от истории чата и наличия нативного
режима целей. Система с фоновыми задачами отображает их через адаптер; другая
система может последовательно продолжать то же сохранённое состояние.

Реализация начинается только из зафиксированного плана с проверенным хешем и
неизменяемого набора пакетов задач. По умолчанию перед выполнением
запрашивается разрешение. Автоматическое выполнение допускается только тогда,
когда это одновременно разрешено политикой зафиксированного запуска и политикой
системы. Изменение контракта, расхождение полномочий, отсутствие доказательств,
исчерпание бюджета или отсутствие обязательной возможности блокирует запуск.

Для попыток с моделью адаптер должен выполнить задачу через выбранный
`attemptModelRoute` или завершиться отказом. Контроллер принимает результат
только если квитанция расхода привязана к запуску, задаче, попытке, отпечатку
плана, исходной ревизии и отпечатку решения маршрутизации.

Уровень SDD выбирается планировщиком, проверяется детерминированными правилами
через `tier resolve`, независимо проверяется `audit-agent-plan` и только после
этого фиксируется контроллером. Ручное переопределение может повысить уровень;
понижение требует согласия resolver и независимой проверки.

## Совместимость и безопасность

- Контракты ядра не содержат имён провайдеров, моделей, путей проектов или
  учётных данных.
- Репозиторий, примеры, фикстуры и проверки не должны содержать информацию
  исходного проекта.
- Адаптеры могут преобразовывать обнаружение возможностей, вызовы, разрешения,
  подагентов и операции среды, но не могут заново реализовывать правила
  жизненного цикла.
- Устанавливайте только доверенные релизы: нативные плагины и hooks могут
  выполнять код с разрешениями, предоставленными системой.
- Перед использованием адаптера проверяйте матрицу поддержки релиза.

## Документация

- [English README](../../README.md)
- [Матрица поддержки адаптеров](../adapters/support-matrix.md)
- [Диагностика готовности](../reference/readiness-diagnostics.md)
- [Проверка завершения](../reference/completion-check.md)
- [Инструкция по продвижению адаптера](../adapters/live-promotion-runbook.md)
- [Проверочный список релиза проверенного адаптера](verified-adapter-release-checklist.md)
- [Modular controller architecture](../architecture/modular-controller.md)
- [Документация плагинов Codex](https://learn.chatgpt.com/docs/build-plugins)
- [Документация плагинов Claude Code](https://code.claude.com/docs/en/plugins)
- [Документация плагинов Cursor](https://cursor.com/docs/plugins)
- [Документация Hermes skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [Skills в OpenCode](https://opencode.ai/docs/skills/)
- [Плагины OpenCode](https://opencode.ai/docs/plugins/)

## Лицензия

Проект распространяется по [Apache License 2.0](../../LICENSE).
