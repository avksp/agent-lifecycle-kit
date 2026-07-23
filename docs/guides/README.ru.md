# Agent Lifecycle Kit

[English version](../../README.md)

Agent Lifecycle Kit — независимый от провайдера набор для управления полным
жизненным циклом агентной разработки: от исходной задачи и проверенной
SDD-спецификации до замороженного плана, контролируемой реализации,
независимого аудита и воспроизводимого финального вердикта.

Набор распространяется как один репозиторий с единым семантическим ядром и
нативными проекциями для Codex, Claude Code, Cursor, Hermes и OpenCode.

## Текущий статус

`v0.2.0` — tagged source release. В репозитории есть корневые publication
manifests для Codex, Claude Code и Cursor, а также projection metadata для
Hermes и OpenCode.

Адаптеры пока имеют статус `EXPERIMENTAL`: есть offline contract coverage и
fail-closed descriptors, но статуса `VERIFIED` нет до появления live install и
lifecycle conformance evidence для каждого host. Публикация в публичных
директориях также зависит от review-процесса каждой платформы.

## Что делает набор

Полный lifecycle выглядит так:

```text
задача
  -> уточнения при необходимости
  -> SDD-спецификация
  -> независимая проверка и улучшение спецификации
  -> production-ready план для агентов
  -> независимая проверка и улучшение плана
  -> неизменяемый freeze
  -> компиляция task packets
  -> авторизованная реализация
  -> controller-owned validation и независимая проверка каждой задачи
  -> исправление или изменение контракта при необходимости
  -> финальный аудит, terminal review и воспроизводимое доказательство завершения
```

Lifecycle содержит пять канонических skills:

- `agent-first-planning`
- `audit-agent-plan`
- `agent-plan-to-workers`
- `agent-workflow-orchestrator`
- `audit-plan-implementation`

Skills остаются тонкими точками входа. Спецификациями, планами, locks, task
packets, состоянием запуска, evidence, бюджетами и правилами аудита управляет
общее детерминированное ядро, а не отдельная реализация в каждом адаптере.

## Compact context mode

Системы с маленьким контекстным окном поддерживаются через детерминированный
профиль контекста, а не через свободное сокращение prompt. В поставке есть
`profiles/small-context-profile.v1.json`: он описывает окна 4k-strict, 8k,
16k, 32k и 64k, резервирует место под ответ, ограничивает active packet и state
summary, ограничивает evidence/tool-output summaries и число последних
verbatim user turns, а также запрещает тихое обрезание.

Если rendered envelope не помещается, controller должен split/refreeze task,
запросить larger context или заблокировать run. Старый контекст и tool output
представляются hashable summaries и evidence identities.

В conformance corpus есть отдельный сценарий `4k-strict`
(`S1-SMALL-CONTEXT-4K-STRICT-01`) поверх базового 8k-сценария, поэтому
поддержка локальных моделей с контекстом меньше 8k проверяется отдельным
контрактным путём.

## Live cost calibration

Synthetic replay baseline полезен для детерминированных regression checks, но
не является production-promotion evidence. Для promotion нужен live receipt с
attested usage, проверенный против
`conformance/core/live-calibration-profile.v1.json` и
`conformance/core/budget-targets.v1.json`.

```bash
python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt <signed-live-calibration-receipt.json> \
  --evidence <live-calibration-evidence.json>
```

Validator отклоняет synthetic replay receipts, отсутствие usage attestation,
unsupported hosts, неполное покрытие required scenario/cohort для этого host,
quality regressions и p95 budget overruns. Для universal `VERIFIED` claim нужен
отдельный passing live receipt по каждому host из calibration profile.
Подробнее:
[live cost calibration](../reference/live-cost-calibration.md).

## Model routing

Model routing — deterministic provider-neutral capability ядра. Ядро выбирает
нейтральный класс модели для lifecycle phase или task attempt, а host adapter
сопоставляет этот класс с конкретной моделью провайдера/локального runtime вне
portable artifacts. Если у task attempt есть
`attemptModelRoute.requiresUsageReceipt=true`, `workflow task-result`
fail-closed до получения валидного host-attested usage receipt.

```bash
agent-lifecycle model profile-check --profile profiles/model-routing-profile.v1.json
agent-lifecycle model route --profile profiles/model-routing-profile.v1.json --request <model-route-request.json>
agent-lifecycle model usage-check --receipt <model-usage-receipt.json> --route-decision <model-route-decision.json> --budget-targets conformance/core/budget-targets.v1.json
```

Portable classes: `no-model`, `budget`, `local-compact`, `standard-code`,
`local-standard-code`, `strong-reasoning`, `local-strong-review` и
`specialist-review`. Local-only режим поддерживается, но final audit, security
review, performance review, production promotion и S2 independent review
требуют явно откалиброванный review-capable local class, например
`local-strong-review`. `local-compact` не может тихо закрывать эти gates.

Подробнее: [model routing](../reference/model-routing.md).

## Структура поставки

Универсальная поставка не означает единый формат manifest. Одно ядро
проецируется в нативную модель загрузки каждой системы:

| Система | Release artifact | Статус |
| --- | --- | --- |
| Codex | `.codex-plugin/plugin.json` и `.agents/plugins/marketplace.json` | Experimental marketplace-ready source projection |
| Claude Code | `.claude-plugin/plugin.json` и `.claude-plugin/marketplace.json` | Experimental marketplace-ready source projection |
| Cursor | `.cursor-plugin/plugin.json` и `.cursor-plugin/marketplace.json` | Experimental source projection для public/team marketplace review |
| Hermes | `skills.sh.json`, общий `skills/` и `adapters/hermes/*` | Experimental direct-skill/tap projection |
| OpenCode | `opencode.json`, общий `skills/` и `adapters/opencode/*` | Experimental local/npm-ready projection metadata |

Корень репозитория — canonical plugin root для Codex, Claude Code и Cursor.
Старые каталоги `adapters/<host>/` остаются offline conformance projections и
host-specific metadata. Пользователям следует устанавливать root package, если
конкретный будущий релиз явно не опубликует materialized adapter package.

## Установка и публикация

### Source-mode core CLI

Для локальной разработки текущего репозитория:

```bash
python -m pip install -e .
agent-lifecycle version
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
agent-lifecycle-neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

Те же команды можно запускать без установки из checkout:

```bash
PYTHONPATH=src python -m agent_lifecycle version
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
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

Сейчас реализованы core CLI groups `version`, `schema`, `workflow status`,
`workflow next`, `workflow block`, `workflow resolve`, `workflow task-start`,
`workflow task-result`, `workflow task-accept`, `workflow finalize`,
`audit ownership`, `tier resolve`, `context profile-check`, `context check`,
`context render`, `model profile-check`, `model route`, `model usage-check`,
`specification check`, `plan check`, `task compile` и `neutrality`.
Lifecycle groups `adapter` и `conformance` остаются
зарезервированными и fail-closed возвращают стабильный
`agent-lifecycle-error.v1`, пока их runtime core modules не реализованы.

`context check` и `context render` также fail-closed при overflow: если
rendered receipt получает `status: FAIL`, CLI завершается с non-zero exit и
возвращает `agent-lifecycle-error.v1` с кодом `context-overflow`. Receipt
проверяет rendered envelope, reserved-output budget, active packet, state
summary, accepted evidence summary, optional `toolOutputs` и число recent
verbatim user turns.

`workflow finalize` требует `--final-audit`. Audit должен пройти с
`READY_FOR_FINALIZATION`, совпадать с `planRevision` и `planDigest` run, не
заявлять production promotion и не содержать unresolved MEDIUM+ findings.

Workflow transitions принудительно проверяют task `controllerGates` для фаз
`pre-launch`, `post-attempt`, `pre-acceptance` и `finalization`. Expected
receipts вычисляются из frozen `receiptPath` template и должны связывать gate,
run, package, task, attempt, phase, operation, plan digest, source revision,
PASS verdict, freshness, dependencies и configured attestation fields.

Тесты используют только Python standard library:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
```

### Codex

Установка из tagged source marketplace:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref v0.2.0
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
```

Настроенные marketplaces также доступны через `/plugins`. После установки
нужно начать новую сессию Codex, чтобы загрузились bundled skills.

Для публикации в публичный OpenAI Plugins Directory нужно отправить root
package как skills-only plugin через OpenAI plugin submission portal. Не
заявляйте статус `VERIFIED`, пока в support matrix нет live Codex install и
lifecycle conformance evidence.

### Claude Code

Добавить marketplace и установить plugin:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
```

В интерактивной Claude Code session эквивалентный slash flow:

```text
/plugin marketplace add avksp/agent-lifecycle-kit
/plugin install agent-lifecycle-kit@agent-lifecycle-kit
/reload-plugins
```

Plugin skills используют namespace имени plugin, например
`/agent-lifecycle-kit:agent-workflow-orchestrator`.

Для включения в Anthropic-managed public directory нужен внешний plugin review
Claude. Repo-level marketplace достаточно для private/community distribution,
но это не public-directory approval claim.

### Cursor

Для локальной проверки перед submission скопируйте или symlink-ните репозиторий
в local plugin directory Cursor:

```bash
mkdir -p ~/.cursor/plugins/local
ln -s /path/to/agent-lifecycle-kit ~/.cursor/plugins/local/agent-lifecycle-kit
```

Затем перезапустите Cursor или выполните `Developer: Reload Window`. После
локальной проверки отправьте public repository на
`https://cursor.com/marketplace/publish`.

Для Teams/Enterprise импортируйте GitHub repo как team marketplace через
Dashboard -> Plugins. После public approval устанавливайте из Cursor
Marketplace или Customize panel. Если ваша сборка Cursor поддерживает
chat-based plugin installation:

```text
/add-plugin agent-lifecycle-kit
```

### Hermes

Hermes может устанавливать общие skills напрямую. Для установки всех lifecycle
skills из tagged release:

```bash
for skill in agent-first-planning audit-agent-plan agent-plan-to-workers agent-workflow-orchestrator audit-plan-implementation; do
  hermes skills install "https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/v0.2.0/skills/${skill}/SKILL.md"
done
```

Корневой `skills.sh.json` содержит tap/category metadata для систем, которые
читают skills.sh-compatible indexes. `adapters/hermes/*` содержит
experimental registry и slash-command projection metadata. Это не live Hermes
plugin verification claim.

### OpenCode

OpenCode загружает plugins и skills разными механизмами. Для project install
скопируйте общие skills и adapter в целевой проект:

```bash
KIT=/path/to/agent-lifecycle-kit
mkdir -p .opencode/skills .opencode/plugins
cp -R "$KIT"/skills/* .opencode/skills/
cp "$KIT"/adapters/opencode/plugins/agent-lifecycle-kit.js .opencode/plugins/
```

Для user-level install:

```bash
KIT=/path/to/agent-lifecycle-kit
mkdir -p ~/.config/opencode/skills ~/.config/opencode/plugins
cp -R "$KIT"/skills/* ~/.config/opencode/skills/
cp "$KIT"/adapters/opencode/plugins/agent-lifecycle-kit.js ~/.config/opencode/plugins/
```

В корне репозитория также есть `opencode.json` для проверки из source
checkout. Будущий npm package может ссылаться на тот же adapter, но `v0.2.0`
не заявляет npm publication.

## Использование

Для полного lifecycle попросите систему запустить
`agent-workflow-orchestrator`:

```text
Используй skill agent-workflow-orchestrator.

Задача: <опиши требуемый результат>.

Задавай только блокирующие уточняющие вопросы. Построй SDD production-ready
план и независимо проверяй его до готовности к freeze. Перед реализацией
запроси разрешение. Проверяй каждый выполненный task независимо от автора.
Перед сообщением о завершении проведи final audit и terminal review.
```

Если система поддерживает явный вызов:

- Codex: выберите Agent Lifecycle Kit или попросите Codex использовать
  `agent-workflow-orchestrator`
- Claude Code: `/agent-lifecycle-kit:agent-workflow-orchestrator`
- Cursor: попросите Agent использовать `agent-workflow-orchestrator`
- Hermes: используйте `/agent-workflow-orchestrator` после установки skill
- OpenCode: попросите агента загрузить `agent-workflow-orchestrator` через
  нативный skill tool

Точный namespaced syntax определяется support matrix конкретного релиза.
Experimental adapter projection не является live runtime compatibility claim.

### Использование отдельных skills

Используйте `agent-first-planning`, когда нужны уточнения, SDD-спецификация и
production-ready план без запуска реализации:

```text
Используй agent-first-planning, чтобы преобразовать задачу в независимо
проверяемый SDD plan package. Остановись до начала реализации.
```

Используйте `audit-agent-plan` для независимой findings-first проверки draft
или reopened плана:

```text
Используй audit-agent-plan для проверки полной revision плана. Не реализуй и
не исправляй его скрытно; верни стабильные findings и readiness verdict.
```

Используйте `agent-plan-to-workers` только после независимой проверки и freeze
плана:

```text
Используй agent-plan-to-workers, чтобы скомпилировать frozen-план в
неизменяемые task packets. Не меняй DAG и ownership.
```

Используйте `agent-workflow-orchestrator` для запуска или продолжения полного
авторизованного lifecycle:

```text
Используй agent-workflow-orchestrator, чтобы продолжить frozen run из durable
state, применить budgets и approvals и провести каждую задачу через review.
```

Используйте `audit-plan-implementation` для read-only аудита task attempt или
всей реализации:

```text
Используй audit-plan-implementation для findings-first аудита относительно
frozen-плана, packet, изменённых файлов, тестов и evidence. Не исправляй
findings.
```

## Выполнение и разрешения

Durable workflow state не зависит от истории чата и наличия нативного goal
mode. Система с background tasks отображает их через адаптер; другая система
может последовательно продолжать то же сохранённое состояние.

Реализация начинается только из hash-verified frozen-плана и неизменяемого
набора task packets. По умолчанию перед выполнением запрашивается разрешение.
Автоматическое выполнение допускается только тогда, когда это одновременно
разрешено frozen run policy и политикой системы. Изменение контракта, drift
полномочий, отсутствие evidence, исчерпание бюджета или отсутствие обязательной
capability блокирует запуск.

Для model-backed attempts адаптер должен выполнить задачу через выбранный
`attemptModelRoute` или fail-closed. Controller принимает result только если
usage receipt привязан к run, task, attempt, plan digest, source revision и
route decision digest.

SDD tier выбирается планировщиком, проверяется deterministic rules через
`tier resolve`, независимо проверяется `audit-agent-plan` и только после этого
freeze-ится controller. Ручной override может повысить tier; понижение требует
согласия resolver и независимого review.

## Совместимость и безопасность

- Core contracts не содержат имён провайдеров, моделей, путей проектов или
  credentials.
- Репозиторий, samples, fixtures и evaluations не должны содержать информацию
  исходного проекта.
- Адаптеры могут преобразовывать discovery, invocation, approvals, subagents и
  host operations, но не могут заново реализовывать lifecycle semantics.
- Устанавливайте только доверенные релизы: нативные plugins и hooks могут
  выполнять код с разрешениями, предоставленными системой.
- Перед использованием адаптера проверяйте support matrix релиза.

## Документация

- [English README](../../README.md)
- [Adapter support matrix](../adapters/support-matrix.md)
- [Modular controller architecture](../architecture/modular-controller.md)
- [Документация плагинов Codex](https://learn.chatgpt.com/docs/build-plugins)
- [Документация плагинов Claude Code](https://code.claude.com/docs/en/plugins)
- [Документация плагинов Cursor](https://cursor.com/docs/plugins)
- [Документация Hermes skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [Skills OpenCode](https://opencode.ai/docs/skills/)
- [Plugins OpenCode](https://opencode.ai/docs/plugins/)

## Лицензия

Проект распространяется по [Apache License 2.0](../../LICENSE).
