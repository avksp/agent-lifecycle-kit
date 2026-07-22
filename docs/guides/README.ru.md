# Agent Lifecycle Kit

[English version](../../README.md)

Agent Lifecycle Kit — независимый от провайдера набор для управления полным
жизненным циклом агентной разработки: от исходной задачи и проверенной
спецификации до замороженного плана, проверенной реализации и
воспроизводимого финального вердикта.

Он распространяется как один репозиторий с единым семантическим ядром и
несколькими нативными адаптерами. Это не только Codex-плагин: Codex, Claude
Code, Cursor, Hermes и OpenCode используют разные модели установки и
возможностей.

> **Статус до первого релиза**
>
> Текущая ветка `main` является release-candidate source tree. В ней есть
> offline adapter projections и source-mode core CLI для workflow, schema,
> tier, compact context, ownership и neutrality проверок. Команды установки
> через marketplaces ниже нельзя считать доступными, пока tagged release не
> опубликует соответствующие manifest-файлы, а support matrix не присвоит
> адаптеру статус `EXPERIMENTAL` или `VERIFIED`.

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
`profiles/small-context-profile.v1.json`: он описывает окна 8k, 16k, 32k и
64k, резервирует место под ответ, ограничивает active packet и state summary и
запрещает тихое обрезание. Если rendered envelope не помещается, controller
должен split/refreeze task, запросить larger context или заблокировать run.

Compact envelope содержит только active role, последнюю пользовательскую
инструкцию, проекцию active task packet, точный write set, acceptance/evidence
ids и структурированную state summary. Старый контекст и tool output
представляются hashable summaries и evidence identities.

## Одна поставка и нативные адаптеры

Универсальная поставка не означает единый формат manifest. Релиз проецирует
одно ядро в нативный формат каждой поддерживаемой системы:

| Система | Нативная проекция релиза | Модель установки |
| --- | --- | --- |
| Codex | `.codex-plugin/plugin.json` и общий `skills/` | Codex marketplace |
| Claude Code | `.claude-plugin/plugin.json`, общий `skills/` и metadata адаптера Claude | Claude plugin marketplace или `--plugin-dir` для разработки |
| Cursor | `.cursor-plugin/plugin.json`, общий `skills/` и metadata адаптера Cursor | Cursor Marketplace и `/add-plugin` |
| Hermes | общий `skills/`, registry/config Hermes и metadata launcher-адаптера | Hermes adapter package или локальная registry/config projection |
| OpenCode | общий `skills/` и JS/TS-адаптер OpenCode | каталоги `.opencode/` или npm plugin в `opencode.json` |
| Другие системы | версионированный adapter contract и conformance suite | нативный пакет конкретной системы |

Первый релиз ориентирован на эти пять систем. Адаптер не получает статус
`VERIFIED` без ограниченного live conformance evidence. Адаптеры, проверенные
только offline, обозначаются как `EXPERIMENTAL`; отсутствие обязательной
security-critical capability приводит к fail-closed остановке.

## Установка

### Source-mode core CLI

Для локальной разработки текущего репозитория:

```bash
python -m pip install -e .
agent-lifecycle version
agent-lifecycle schema list
agent-lifecycle workflow status --state <path-to-run.state.json>
agent-lifecycle workflow next --state <path-to-run.state.json>
agent-lifecycle workflow task-start --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --reason "<reason>"
agent-lifecycle workflow task-result --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --result <task-result.json> --reason "<reason>"
agent-lifecycle workflow task-accept --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --review <task-review.json> --reason "<reason>"
agent-lifecycle audit ownership --manifest <plan.manifest.json> --base <base-ref> --fail-on-unowned --fail-on-forbidden
agent-lifecycle tier resolve --request <tier-request.json>
agent-lifecycle context profile-check --profile profiles/small-context-profile.v1.json
agent-lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
agent-lifecycle-neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

Те же команды можно запускать без установки из checkout:

```bash
PYTHONPATH=src python -m agent_lifecycle version
PYTHONPATH=src python -m agent_lifecycle schema list
PYTHONPATH=src python -m agent_lifecycle workflow status --state <path-to-run.state.json>
PYTHONPATH=src python -m agent_lifecycle workflow next --state <path-to-run.state.json>
PYTHONPATH=src python -m agent_lifecycle workflow task-start --state <path-to-run.state.json> --task <task-id> --operation-id <id> --expected-revision <n> --source-revision <sha> --reason "<reason>"
PYTHONPATH=src python -m agent_lifecycle audit ownership --manifest <plan.manifest.json> --base <base-ref> --fail-on-unowned --fail-on-forbidden
PYTHONPATH=src python -m agent_lifecycle tier resolve --request <tier-request.json>
PYTHONPATH=src python -m agent_lifecycle context check --profile profiles/small-context-profile.v1.json --task-packet <task-packet.json> --summary <compact-summary.json> --target-window 8k
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

Сейчас реализованы core CLI groups `version`, `schema`, `workflow status`,
`workflow next`, `workflow block`, `workflow resolve`, `workflow task-start`,
`workflow task-result`, `workflow task-accept`, `audit ownership`,
`tier resolve`, `context profile-check`, `context check`, `context render` и
`neutrality`. Остальные
lifecycle groups зарезервированы и fail-closed возвращают стабильный
`agent-lifecycle-error.v1`, пока их core modules не реализованы.

Тесты используют только Python standard library:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
```

### Codex

После публикации release marketplace:

```bash
codex plugin marketplace add <marketplace-repository-or-local-root>
codex plugin add agent-lifecycle-kit@<marketplace-name>
```

Настроенные marketplaces также доступны через `/plugins`. После установки
нужно начать новую сессию Codex, чтобы загрузились skills и адаптер.

### Claude Code

Для опубликованного marketplace:

```bash
claude plugin marketplace add <marketplace-repository-or-local-root>
claude plugin install agent-lifecycle-kit@<marketplace-name>
```

Для локальной разработки после появления Claude manifest:

```bash
claude --plugin-dir <path-to-agent-lifecycle-kit>
```

После установки или изменения локального плагина выполните
`/reload-plugins`. Skills Claude-плагина используют namespace имени плагина.

### Cursor

После публикации адаптера в Cursor Marketplace выполните в Cursor Agent chat:

```text
/add-plugin agent-lifecycle-kit
```

В support matrix релиза будет указана минимальная проверенная версия Cursor и
результат lifecycle canary для локальной установки.

### Hermes

Hermes использует общие lifecycle skills через Hermes-specific registry или
configuration projection плюс launcher-адаптер. Точный локальный registry path,
package name и invocation syntax будут задокументированы только после того,
как Hermes artifact будет создан и пройдёт Hermes conformance suite.

До этого Hermes является обязательной целью adapter-контракта standalone
release, но не verified runtime claim.

### OpenCode

OpenCode не использует manifest от Codex, Claude или Cursor. Релиз будет
содержать OpenCode-проекцию с каноническими skills и runtime-адаптером. Для
установки на уровне проекта она размещается в:

```text
.opencode/skills/<skill-name>/SKILL.md
.opencode/plugins/agent-lifecycle-kit.{js,ts}
```

Для пользовательской установки используются соответствующие каталоги:

```text
~/.config/opencode/skills/<skill-name>/SKILL.md
~/.config/opencode/plugins/agent-lifecycle-kit.{js,ts}
```

Если адаптер будет опубликован в npm, его можно будет указать в
`opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["<published-opencode-adapter-package>"]
}
```

Точная команда копирования/установки и имя пакета появятся только после того,
как соответствующий release artifact будет создан и пройдёт OpenCode
conformance suite.

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

- Codex: выберите установленный плагин или его skill через `@` либо попросите
  Codex использовать `agent-workflow-orchestrator` из Agent Lifecycle Kit
- Claude Code: `/agent-lifecycle-kit:agent-workflow-orchestrator`
- Cursor: попросите Agent использовать `agent-workflow-orchestrator`
- Hermes: попросите Hermes загрузить `agent-workflow-orchestrator` через
  настроенный lifecycle-kit registry или launcher-адаптер
- OpenCode: попросите агента загрузить `agent-workflow-orchestrator` через
  нативный skill tool

Точный namespaced syntax определяется support matrix конкретного релиза.
Pre-release пример не является заявлением о совместимости invocation.

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

- [English README](README.md)
- [Modular controller architecture](docs/architecture/modular-controller.md)
- [Документация плагинов Codex](https://learn.chatgpt.com/docs/build-plugins)
- [Документация плагинов Claude Code](https://code.claude.com/docs/en/plugins)
- [Документация плагинов Cursor](https://cursor.com/docs/plugins)
- [Документация Hermes skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [Skills OpenCode](https://opencode.ai/docs/skills/)
- [Plugins OpenCode](https://opencode.ai/docs/plugins/)

## Лицензия

Проект распространяется по [Apache License 2.0](LICENSE).
