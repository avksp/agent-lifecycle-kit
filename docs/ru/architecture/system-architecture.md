# Архитектура системы

Этот документ описывает Agent Lifecycle Kit (ALK) как нейтральный к
провайдерам контроллер жизненного цикла для задач кодовых агентов. Структура
описания следует уровням C4 и добавляет уровень C0 для миссии проекта:

- C0 описывает миссию и границы ответственности.
- C1 показывает ALK во внешнем окружении.
- C2 делит проект на крупные исходные и рабочие части.
- C3 показывает компоненты внутри пакета выполнения.
- C4 называет основные маршруты вызова на уровне кода.

Подробная англоязычная карта модулей находится в
`docs/architecture/modular-controller.md`. Этот документ объясняет, как части
системы взаимодействуют в рабочих сценариях.

## C0: контекст миссии

ALK нужен, чтобы провести задачу от запроса до проверяемого завершения и при
этом не превратить ядро жизненного цикла в ещё одну среду выполнения кодового
агента. ALK задаёт контракты, переходы состояния, контрольные точки и
подтверждения. Хостовые CLI по-прежнему выполняют модельную работу,
редактирование и инструменты.

```mermaid
flowchart LR
  operator[Оператор или обёртка хоста]
  request[Задача, тикет, план, PR или MR]
  alk[Agent Lifecycle Kit]
  hosts[CLI хоста и модели]
  repo[Репозиторий]
  evidence[Подтверждения и финальное доказательство]

  operator --> request
  request --> alk
  alk --> evidence
  alk --> repo
  operator --> hosts
  hosts --> repo
  hosts --> evidence
  evidence --> alk
```

Главное архитектурное правило - разделение полномочий:

- ALK владеет источником правды жизненного цикла: спецификацией, планом,
  состоянием, подтверждениями, контрольными точками и финальным доказательством.
- Репозиторий владеет исходным кодом, тестами, документацией и метаданными
  релиза.
- Адаптеры владеют проекцией команд хоста, границами окружения и локальными
  профилями запуска.
- Хосты владеют выполнением модели и учётными данными провайдера.
- Проверяющие владеют смысловой оценкой; ALK фиксирует и проверяет
  подтверждения этой оценки.

## C1: системный контекст

На системном уровне ALK - это локальная CLI-команда и Python-пакет внутри
исходного дерева. Он читает и записывает структурированные артефакты, но не
требует сервера, фонового процесса, базы данных или API провайдера.

```mermaid
flowchart TB
  user[Пользователь или автоматизация]
  cli[agent-lifecycle CLI]
  source[Исходное дерево]
  adapters[Дескрипторы адаптеров]
  host[CLI хоста: Codex, Claude, Cursor, OpenCode, Goose, Pi и другие]
  ci[CI и релизные проверки]
  docs[Документация и навыки]
  local[Локальные настройки и секреты хоста]

  user --> cli
  cli --> source
  cli --> adapters
  cli --> docs
  source --> ci
  adapters --> host
  local -. зона хоста .-> host
  host --> source
  host --> cli
```

Важные границы:

- Переносимые артефакты не должны хранить сырые секреты, приватные значения
  окружения или локальные абсолютные пути.
- `adapter task start` принимает обычный текст или Markdown только как
  черновой вход.
- Управляемое выполнение требует зафиксированный запрос запуска или
  зафиксированный план, связанный с состоянием рабочего цикла.
- Дополнительная групповая проверка остаётся хостовой: ALK готовит назначения,
  импортирует очищенные результаты, объединяет выводы и проверяет кворум.

## C2: крупные части

Проект поставляется как исходный код. В этом разделе "части" означают исходные
и рабочие области, а не Docker-сервисы.

```mermaid
flowchart TB
  subgraph package[Python-пакет: src/agent_lifecycle]
    cli[Разбор команд и маршрутизация]
    contracts[Контракты и схемы]
    domain[Сервисы жизненного цикла]
    adapters_runtime[Сессии адаптеров]
    reporting[Отчёты без записи]
  end

  subgraph source[Файлы репозитория]
    adapter_files[adapters/* дескрипторы и манифесты]
    docs[docs, skills и templates]
    tests[tests и релизные валидаторы]
    release[Метаданные релиза]
  end

  subgraph local[Локальная граница хоста]
    host_cli[Процессы CLI хоста]
    host_env[Файлы окружения и учётные данные]
    raw_receipts[Игнорируемые сырые подтверждения]
  end

  cli --> contracts
  cli --> domain
  cli --> adapters_runtime
  cli --> reporting
  domain --> contracts
  adapters_runtime --> adapter_files
  adapters_runtime --> contracts
  reporting --> contracts
  source --> tests
  host_env --> host_cli
  host_cli --> raw_receipts
  raw_receipts --> domain
```

| Часть | Ответственность | Не должна делать |
| --- | --- | --- |
| `src/agent_lifecycle/cli` | Разобрать аргументы, направить команду, вывести стабильный JSON или текстовый прогресс. | Хранить смысл жизненного цикла или логику провайдера. |
| `src/agent_lifecycle/contracts` | Публичные схемы, канонический JSON, отпечатки, типовые ошибки и правила совместимости. | Зависеть от CLI хоста. |
| Доменные пакеты | Планирование, рабочий цикл, аудит, контекст, метрики, качество, групповая проверка и отчёты. | Напрямую вызывать API провайдера. |
| `src/agent_lifecycle/adapter_sessions` | Сессии по дескрипторам, приём задачи и мост к управляемому запуску. | Вставлять промпты в хост или разбирать телеметрию хоста в ядре. |
| `adapters/*` | Дескрипторы хостов, проекции операций, манифесты поддержки и резюме подтверждений. | Менять схемы жизненного цикла. |
| `tools/release` и тесты | Релизные проверки, валидаторы, совместимость и документационные контрольные точки. | Повышать зрелость адаптера по синтетическим данным. |

## C3: карта компонентов выполнения

```mermaid
flowchart LR
  cli[cli]
  contracts[contracts]
  changesets[changesets]
  compiler[compiler]
  planning[planning и specification]
  freeze[freeze]
  workflow[Рабочий цикл]
  audit[audit]
  adapter_sessions[adapter_sessions]
  host_protocol[host_protocol]
  review_mesh[review_mesh]
  reporting[reporting]
  metrics[metrics и policy]
  context[context и evidence]
  quality[quality]
  neutrality[neutrality]
  runner[Контроллер выполнения]
  worktree[worktree]

  cli --> planning
  cli --> compiler
  cli --> workflow
  cli --> audit
  cli --> adapter_sessions
  cli --> review_mesh
  cli --> reporting
  cli --> metrics
  cli --> context
  cli --> neutrality
  cli --> runner
  cli --> worktree
  planning --> contracts
  compiler --> contracts
  freeze --> contracts
  workflow --> contracts
  workflow --> audit
  workflow --> quality
  workflow --> review_mesh
  workflow --> neutrality
  adapter_sessions --> workflow
  adapter_sessions --> host_protocol
  adapter_sessions --> planning
  review_mesh --> contracts
  review_mesh --> metrics
  audit --> workflow
  audit --> changesets
  audit --> review_mesh
  reporting --> workflow
  metrics --> contracts
  context --> contracts
  neutrality --> contracts
  runner --> workflow
  runner --> worktree
  worktree --> contracts
```

| Компонент | Основные модули | Когда вызывается |
| --- | --- | --- |
| Маршрутизация CLI | `cli/main.py`, `cli/parsers.py`, `cli/dispatch.py`, `cli/dispatch_adapters.py`, `cli/dispatch_contracts.py`, `cli/dispatch_lifecycle.py`, `cli/dispatch_observability.py`, `cli/dispatch_planning.py`, `cli/adapter.py` | Любая команда `agent-lifecycle ...` начинается здесь; корневой диспетчер выбирает специализированный обработчик группы команд. |
| Контракты | `contracts/*` | Все публичные подтверждения, схемы, отпечатки и проверочные конверты. |
| Поиск изменений | `changesets/git.py` | Аудит владения и реализации по Git-изменениям. |
| Компиляция заданий | `compiler/task_packets.py`, `compiler/small_model_packets.py` | Преобразование зафиксированного графа задач в рабочие и компактные пакеты. |
| Планирование | `planning/*`, `specification/*`, `freeze/locks.py` | SDD-уровень, проверка плана, полнота, приёмка и файл блокировки. |
| Рабочий цикл | `workflow/*` | Изменение состояния, переходы задач, финализация и следующий управляемый шаг. |
| Сессии адаптеров | `adapter_sessions/*` | `adapter session`, `adapter task start`, `adapter run`, проверка локального профиля и явный запуск внешнего процесса из зафиксированного состояния. |
| Протокол хоста | `host_protocol/*` | Проверка адаптера, безопасный осмотр, захват событий и возможности. |
| Аудит | `audit/*` | Владение файлами, вердикты проверки, аудит реализации, целостность доказательств. |
| Групповая проверка | `review_mesh/*` | Рекомендация, шаблоны оператора, подготовка пакетов проверяющих, назначения, импорт результатов, объединение выводов и кворум. |
| Отчёты | `reporting/*` | Статус, лента событий, прогресс, счётчик изменений и мост прогресса. |
| Метрики и правила | `metrics/*`, `policy/*`, `model_routing/*` | Экспорт расхода, политика токенов/ресурсов, локальная статистика и классы моделей. |
| Контекст и подтверждения | `context/*`, `evidence_index/*`, `goal/*`, `followup/*` | Компактные пакеты, поиск по эпизодам, импорт внешнего контекста, представление цели и продолжения. |
| Нейтральность | `neutrality/scanner.py`, `neutrality/paths.py`, `neutrality/receipt.py`, `neutrality/gate.py` | Привязанная к индексу Git проверка выпуска, явное включение локальных подтверждений из разрешённых корней, устойчивое чтение, проверка полномочий и подписанные квитанции. |
| Контроллер выполнения | `runner/*` | Ограниченное состояние цикла выполнения поверх существующего рабочего цикла. |
| Рабочее дерево | `worktree/*`, `cli/worktree.py` | Правила изоляции рабочего дерева и подтверждения попыток. |

## C4: маршруты вызова на уровне кода

Уровень C4 ниже называет конкретные функции и модули. Он ограничен теми
маршрутами, которые реально использует оператор.

### Маршрутизация команды

```mermaid
sequenceDiagram
  participant User as Пользователь
  participant Main as cli/main.py
  participant Parser as cli/parsers.py
  participant Dispatch as cli/dispatch.py
  participant Handler as cli/dispatch_*.py
  participant Service as Доменный сервис
  participant Contracts as contracts/*

  User->>Main: agent-lifecycle <command>
  Main->>Parser: build_parser()
  Main->>Dispatch: dispatch(args, remainder)
  Dispatch->>Handler: выбор группы команд
  Handler->>Service: вызов выбранного сервиса
  Service->>Contracts: проверка, отпечаток, чтение и запись JSON
  Service-->>Handler: типизированное подтверждение или отчёт
  Handler-->>Dispatch: JSON-совместимый объект
  Dispatch-->>Main: JSON-совместимый объект
  Main-->>User: стабильный JSON в stdout
```

Паттерн: диспетчер команд и функциональное ядро. `cli/dispatch.py` выбирает
единую команду запуска или один из пяти обработчиков групп: адаптеры и
готовность, контракты и подтверждения, жизненный цикл, наблюдаемость или
планирование. Модули командной строки остаются тонкими; поведение и тесты живут
в доменных сервисах.

### Единая команда запуска жизненного цикла

```mermaid
sequenceDiagram
  participant User as Пользователь
  participant StartCLI as cli/start.py
  participant Start as adapter_sessions/unified_start.py
  participant Intake as adapter_sessions/task_intake.py
  participant Resume as adapter_sessions/workflow_bridge.py
  participant Store as adapter_sessions/session_store.py
  participant LocalLaunch as adapter_sessions/launcher.py
  participant Process as adapter_sessions/process.py

  User->>StartCLI: start --adapter --file|--text|--resume [--launch]
  StartCLI->>Start: start_lifecycle()
  alt обычная задача в auto/research/plan/review
    Start->>Intake: start_adapter_task()
    Intake-->>Start: проверяемый черновик
  else зафиксированный ввод и явный implement
    Start->>Intake: существующая передача управляемому шагу
    Intake-->>Start: подтверждение управляемого шага
    opt явный запуск по локальному профилю
      Start->>LocalLaunch: launch_from_local_profile(идентичность, профиль риска)
      LocalLaunch->>Process: run_process(argv, shell=false, ограниченное время)
      Process-->>LocalLaunch: очищенный результат процесса
    end
  else сохранённая сессия ALK
    Start->>Store: load_session()
    Start->>Resume: resume_adapter_session()
    Resume-->>Start: результат проверки происхождения
  end
  Start-->>User: agent-lifecycle-start-receipt.v1
```

Фасад выбирает существующий примитив и не владеет переходами рабочего цикла.
Обычные режимы задачи не могут вызвать управляемое выполнение или запуск
внешнего инструмента. Передача зафиксированного входа требует явного режима
`implement` и полной привязки. Возобновление принимает только сохранённую
сессию ALK, проверяет адаптер и происхождение состояния и не трактует значение
как идентификатор диалога внешнего инструмента. Локальный процесс доступен
только при дополнительном явном указании `--launch --host-launch-profile` после
проверки файла блокировки, происхождения и профиля риска. Общий запуск через
дескриптор и запуск интерактивной сессии остаются заблокированными.

### Приём обычной задачи или Markdown

```mermaid
sequenceDiagram
  participant User as Пользователь
  participant AdapterCLI as cli/adapter.py
  participant Intake as adapter_sessions/task_intake.py
  participant Import as imports/planning.py
  participant Advisor as review_mesh/recommendation.py
  participant BugAdvisor as quality/bug_forensics_advisor.py
  participant Out as agent-adapter-task-start-receipt.v1

  User->>AdapterCLI: adapter task start --file task.md
  AdapterCLI->>Intake: start_adapter_task()
  Intake->>Import: import_planning_input()
  Intake->>Advisor: recommend_review_mesh_for_text()
  Intake->>BugAdvisor: build_bug_forensics_advisory()
  Intake-->>Out: REVIEW_REQUIRED или BLOCKED
```

Этот маршрут используется для обычного текста задачи, Markdown, пакетов
проверки кода и импортированного планирования. Он не запускает реализацию.
Подтверждение хранит метку источника, отпечаток и размер в байтах, но не
исходный текст. Рекомендации групповой проверки и расследования ошибок остаются
подсказками, пока проверенный и зафиксированный план не включит обязательные
контрольные точки.

### Управляемый запуск адаптера

```mermaid
sequenceDiagram
  participant User as Пользователь
  participant AdapterCLI as cli/adapter.py
  participant Bridge as adapter_sessions/workflow_bridge.py
  participant Runner as workflow/managed_runner.py
  participant Workflow as workflow/next_action.py
  participant Progress as reporting/progress_hooks.py

  User->>AdapterCLI: adapter run --state --manifest --task
  AdapterCLI->>Bridge: managed_adapter_run()
  Bridge->>Runner: run_managed_lifecycle_step()
  Runner->>Workflow: build_managed_next_action()
  AdapterCLI->>Progress: stderr или подтверждение прогресса
  Runner-->>User: agent-adapter-session-receipt.v1
```

Маршрут вызывается только при наличии зафиксированного плана и привязки к
состоянию рабочего цикла. ALK возвращает следующий шаг жизненного цикла, но не
становится средой выполнения модели.

### Изменение состояния рабочего цикла

```mermaid
sequenceDiagram
  participant CLI
  participant Transition as workflow/task_transitions.py
  participant Gates as workflow/gates.py
  participant Kernel as workflow/operation_kernel.py
  participant Events as workflow/events.py
  participant State as workflow/state.py

  CLI->>Transition: start_task / commit_task_result / accept_task
  Transition->>Kernel: load_for_update(operationId, expectedRevision)
  Kernel->>State: load_state()
  Kernel->>State: проверка ревизии и operation id
  Transition->>Gates: validate_controller_gates()
  Transition->>Kernel: commit_state()
  Kernel->>Events: append_event()
  Kernel->>State: write_state_replace()
```

Паттерны: конечный автомат, ядро операции, оптимистичная проверка ревизии,
ключ идемпотентности и добавляемый журнал событий. Команды, меняющие состояние,
отказывают при устаревшей ревизии, повторном operation id и отсутствии
обязательных подтверждений.

### Проверка изменений GitHub или GitLab

```mermaid
flowchart LR
  pr[PR GitHub или MR GitLab]
  diff[Файл изменений]
  task[review-task.md]
  intake[adapter task start]
  advice[review-mesh recommend]
  reviewers[Проверяющие на стороне хоста]
  synthesis[import, synthesize, quorum]

  pr --> diff
  diff --> task
  task --> intake
  intake --> advice
  advice --> reviewers
  reviewers --> synthesis
```

Маршрут используется, когда оператору нужна структурированная проверка
локальной ветки, запроса на слияние в GitHub или запроса на слияние в GitLab.
Работа с Git остаётся вне ALK; ALK получает стабильный пакет проверки.

### Дополнительная групповая проверка

```mermaid
sequenceDiagram
  participant CLI
  participant Profile as review_mesh/contracts.py
  participant Templates as review_mesh/operator_templates.py
  participant Assign as review_mesh/assignments.py
  participant Host as Проверяющий хост
  participant Import as review_mesh/results.py
  participant Synth as review_mesh/synthesis.py
  participant Quorum as review_mesh/quorum.py

  CLI->>Profile: build_review_mesh_profile()
  CLI->>Templates: prepare_review_mesh_packets()
  CLI->>Assign: build_review_mesh_assignment_packet()
  Assign-->>Host: пакет назначения
  Host-->>CLI: reviewer-output.v1
  CLI->>Import: import_review_mesh_result()
  CLI->>Synth: synthesize_review_mesh_results()
  CLI->>Quorum: build_quorum_from_synthesis()
```

Маршрут используется для проверки черновика ведущего, параллельного
исследования или группы аудиторов реализации. Ядро не запускает проверяющих.
Кворум блокирует этап только тогда, когда зафиксированный план явно включил это
требование.

### Аудит реализации

```mermaid
sequenceDiagram
  participant CLI
  participant Audit as audit/implementation.py
  participant State as workflow/state.py
  participant Review as workflow/reviews.py
  participant Ownership as audit/ownership.py
  participant Gates as workflow/review_mesh_gate.py

  CLI->>Audit: audit implementation
  Audit->>State: load_state()
  Audit->>Review: validate_task_result() и validate_task_review()
  Audit->>Ownership: build_ownership_report()
  Audit->>Gates: validate_review_mesh_quorum_path()
  Audit-->>CLI: agent-implementation-audit-report.v1
```

Маршрут вызывается после попытки реализации, когда уже есть результат задачи и
независимая проверка. Он проверяет происхождение, владение файлами,
подтверждения, покрытие критериев приёмки, песочницу и необязательный кворум
групповой проверки.

### Прогресс и отчёты без записи

```mermaid
flowchart LR
  state[Состояние рабочего цикла]
  usage[Подтверждения расхода]
  changes[Сводка изменений]
  progress[reporting/progress_view.py]
  terminal[reporting/progress_terminal.py]
  bridge[reporting/progress_bridge.py]

  state --> progress
  usage --> progress
  changes --> progress
  progress --> terminal
  progress --> bridge
```

Маршрут вызывается командами `report progress`, `report progress-bridge` и
хуками прогресса у управляемых команд рабочего цикла. Отчёты не меняют
состояние, не запускают модель и не разбирают хостовую телеметрию в ядре.

### Проверка нейтральности выпуска

```mermaid
sequenceDiagram
  participant Operator as Оператор
  participant CLI as neutrality/cli.py
  participant Policy as neutrality/policy.py
  participant Scanner as neutrality/scanner.py
  participant Paths as neutrality/paths.py
  participant Receipt as neutrality/receipt.py или gate.py

  Operator->>CLI: scan/bootstrap --scope tracked-release
  CLI->>Policy: загрузить localArtifactRoots и ограничения
  CLI->>Scanner: scan_repository
  Scanner->>Scanner: git ls-files --stage --cached и HEAD
  Scanner->>Paths: устойчивое чтение с одной повторной попыткой
  opt include-local-artifacts
    Scanner->>Paths: проверить разрешённые относительные корни
  end
  Scanner-->>CLI: отчёт с scopeBinding и subjectDigest
  opt подписанный маршрут
    CLI->>Receipt: связать claims и обязательные счётчики
  end
```

Релизные процессы используют `tracked-release` без локальных материалов.
Отдельный шаг с подтверждениями может явно включить корни, объявленные в
политике. Старые области сохраняют прежний обход, но получают подписанную
отметку об устаревании.

## Варианты работы и маршрутизация вызовов

| Вариант | Команда оператора | Основные модули | Результат |
| --- | --- | --- | --- |
| Проверка готовности | `diagnose --no-install-plans` | `diagnostics/readiness.py`, `host_protocol/*`, `context/*` | Очищенный отчёт готовности. |
| Проверка адаптера | `adapter validate/inspect/install-plan` | `cli/adapter.py`, `host_protocol/*`, `diagnostics/readiness.py` | Проверка, безопасный осмотр или пробный план установки. |
| Приём обычной задачи | `adapter task start --file/--text` | `adapter_sessions/task_intake.py`, `imports/planning.py`, `review_mesh/recommendation.py`, `quality/bug_forensics_advisor.py` | Черновое подтверждение, требующее проверки. |
| Проверка плана | `plan check`, `plan completeness-check`, `plan acceptance-check` | `planning/*`, `freeze/locks.py` | PASS/FAIL подтверждение плана. |
| Управляемый следующий шаг | `workflow run` или `adapter run` | `workflow/managed_runner.py`, `workflow/next_action.py`, `adapter_sessions/workflow_bridge.py` | Подтверждение следующего шага без запуска хоста. |
| Изменение задачи | `workflow task-start/task-result/task-accept` | `workflow/task_transitions.py`, `workflow/operation_kernel.py`, `workflow/gates.py` | Обновлённое состояние и журнал событий. |
| Аудит реализации | `audit implementation` | `audit/implementation.py`, `audit/ownership.py`, `workflow/reviews.py` | Отчёт аудита реализации. |
| Групповая проверка | `review-mesh profile/recommend/prepare/assign/import-result/synthesize/quorum` | `review_mesh/*`, `model_routing/profiles.py`, `quality/cross_check.py` | Рекомендация, подготовленные пакеты проверяющих, назначения, результаты, объединение выводов и кворум. |
| Проверка кода | Git/CLI хоста и `adapter task start` | Git вне ALK, затем `adapter_sessions/task_intake.py` и при необходимости `review_mesh/*` | Приём пакета проверки и необязательный кворум. |
| Исправление дефекта | `adapter task start` и контрольные точки зафиксированного плана | `adapter_sessions/task_intake.py`, `quality/bug_forensics_advisor.py`, `quality/bug_forensics.py`, `audit/bug_forensics.py`, `workflow/bug_forensics_gates.py` | Рекомендация профиля дефекта, затем обязательные подтверждения по плану. |
| Внешний контекст | `context external-import` и поиск по эпизодам | `context/external_memory.py`, `evidence_index/external_context.py`, `evidence_index/episode_index.py` | Необязательные подсказки контекста без права заменять доказательства. |
| Статус цели | `goal view` | `goal/view.py`, `reporting/progress_view.py`, `workflow/query.py` | Представление цели и прогресса без записи. |
| Отображение прогресса | `report progress`, `report progress-bridge`, хуки прогресса | `reporting/*`, `cli/progress_hooks.py` | Текстовый или JSON-прогресс без вызова модели. |
| Проверка релиза | Релизные инструменты и тесты | `tools/release/*`, `contracts/release_contract_schemas.py`, docs/tests | Проверка исходного релиза и подтверждений. |

## Используемые паттерны

| Паттерн | Где используется | Зачем нужен |
| --- | --- | --- |
| Порты и адаптеры | `adapters/*`, `host_protocol/*`, `adapter_sessions/*` | Держать команды хоста, секреты и возможности вне ядра жизненного цикла. |
| Контракты сначала | `contracts/*`, `schemas.py`, публичные `.v1` подтверждения | Делать каждое заявление жизненного цикла машинно проверяемым и переносимым. |
| Диспетчер команд | `cli/main.py`, `cli/parsers.py`, `cli/dispatch.py`, `cli/dispatch_*.py` | Оставлять корневой CLI тонким и направлять каждую группу команд в её доменный обработчик. |
| Функциональное ядро и императивная оболочка | Функции создания и проверки возвращают словари; CLI работает с путями и выводом. | Упростить тестирование и чтение небольшими моделями. |
| Конечный автомат | `workflow/state.py`, `workflow/task_transitions.py`, `runner/core.py` | Сделать фазы жизненного цикла явными и отказывать при недопустимых переходах. |
| Ядро операции | `workflow/operation_kernel.py` | Централизовать проверку ревизии, идемпотентность и запись состояния/событий. |
| Цепочка контрольных точек | `workflow/gates.py`, контрольные точки аудита, завершения и кворума | Не принимать работу и не финализировать запуск без обязательных подтверждений. |
| Стратегия и политика | `policy/*`, `model_routing/*`, `metrics/recommendations.py` | Выбирать безопасный маршрут жизненного цикла и класс модели без привязки к провайдеру. |
| Фасад | `audit/implementation.py`, `diagnostics/bundles.py`, `reporting/*` | Собрать несколько проверок в один типизированный отчёт без дублирования нижних уровней. |
| Пара создания и проверки | Большинство контрактных модулей и релизных валидаторов | Детерминированно создать подтверждение и независимо его проверить. |
| Отказ при сомнении | Импорт, запуск адаптера, импорт результата проверки, релизные контрольные точки | Отказывать при небезопасном или неподтверждённом пути вместо догадок. |

## Архитектурные правила

- Смысл жизненного цикла находится в доменных пакетах, а не в адаптерах или
  отображении CLI.
- Адаптеры описывают возможности хоста и локальные границы запуска, но не
  владеют правдой рабочего цикла.
- Сырой вход никогда не является полномочием на выполнение.
- Рекомендация не является контрольной точкой. Контрольная точка появляется
  только после явного включения в зафиксированном плане.
- Представления без записи не меняют состояние и не запускают модель.
- Расход и прогресс используют токены и ресурсы; денежная стоимость
  необязательна и принимается только если её сообщает тарифицируемый хост.
- Публичные заявления релиза должны опираться на отслеживаемые резюме и, когда
  нужно, на локальные очищенные подтверждения реального хоста.

## Связанные документы

- [Источник правды](../reference/source-of-truth.md)
- [Управляемые сессии адаптеров](../reference/managed-adapter-sessions.md)
- [Аудит реализации](../reference/implementation-audit.md)
- [Практические сценарии групповой проверки](../review-mesh-workflow.md)
- [Сценарии проверки кода](../code-review-workflows.md)
- [Внешний контекст памяти](../reference/external-memory.md)
- [Непрерывность цели](../reference/goal-continuity.md)
- [Профиль расследования ошибок](../reference/bug-forensics.md)
- [Проверка нейтральности](../reference/neutrality.md)

Дополнительные англоязычные архитектурные документы: `docs/architecture/release-architecture.md`,
`docs/architecture/runner-transition-contract.md` и
`docs/architecture/runner-extension-map.md`.
