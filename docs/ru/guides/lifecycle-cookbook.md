# Сценарии задач жизненного цикла

Raw input остаётся draft-only до разрешения reviewed authority.

## Канонический маршрут выполнения

Известный маршрут вызывайте прямо с bound arguments, например:
`agent-lifecycle start --adapter codex --mode research --file work/tasks/research.md --out work/tasks/research-start.json`.
Если implementation transition неизвестен, сначала project `workflow continue`, затем apply с теми же revision/action digest. Для этого маршрута читайте [продолжение workflow](../reference/workflow-continuation.md). Existing `--until-blocked --apply` требует ready explicit bundle и positive transition/I/O caps и останавливается до model, host, reviewer, operator или plan-authority work. Direct `workflow task-*` допустим.
Legacy `runner` receipts — read-only compatibility journals; они не разрешают выполнение, acceptance или finalization. Прикрепляйте их как evidence к workflow.

Fast feedback выполняется до mandatory acceptance checks и полного quality floor. `FULL_REQUIRED` требует repair/plan review, а не whole-repository audit. При неизменном external `WAITING` blocker сохраните handoff и ждите события; не перезапускайте модель, discovery или неизменную успешную проверку.

## Выбор сценария

Читайте общий маршрут, таблицу, [правила безопасности](#правила-безопасности), выбранный recipe и его required links. Если stage неизвестен, проверьте durable state; меняйте recipe при смене stage. Полный hash-bound role contract, frozen plan, active packet и shared contracts обязательны. [Полный lifecycle contract orchestrator](https://github.com/avksp/agent-lifecycle-kit/blob/main/skills/agent-workflow-orchestrator/references/lifecycle-contract.md) остаётся обязательным. [Локальный профиль письма](controlled-technical-english.md) содержит термины, role suitability для assigning controller и границы измерения.

| Задача | Сценарий |
| --- | --- |
| Research/plan, включая S0/S2 authoring | [Только исследование и планирование](#только-исследование-и-планирование) |
| Один task file | [Проверка одного Markdown-файла](#проверка-одной-задачи-markdown) |
| Plan folder | [Проверка папки с Markdown-планом](#проверка-папки-плана-markdown) |
| Code или PR/MR | [Проверка изменений кода](#проверка-изменений-кода) |
| Completed work | [Аудит подтверждений реализации](#аудит-подтверждений-реализации) |
| Исправления review | [Remediation attempt](#новая-попытка-доработки) |
| Defect | [Bug Forensics repair](#исправление-с-bug-forensics) |
| Несколько reviewers | [Согласованная перепроверка](#групповая-проверка) |
| Active run | [Цель и прогресс](#цель-и-прогресс) |
| Opted-in risk-aware task | [Запуск с учётом риска](#задача-с-учётом-риска) |
| v4 task transition | [Workflow v4](#использование-task-local-workflow-v4) |
| Recovery | [Восстановление](#восстановление-запуска-без-ручной-записи-состояния) |
| New capability before freeze | [Проверка достижимости](#достижимость-возможности-до-freeze) |

## Только исследование и планирование

Сохраните задачу в файле и запустите режим исследования:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode research \
  --file work/tasks/research.md \
  --out work/tasks/research-start.json

agent-lifecycle review-mesh recommend \
  --file work/tasks/research.md \
  --out work/tasks/research-recommendation.json
```

Если нужен только анализ, на этом работа заканчивается. Для реализации
преобразуйте принятый план в обычный пакет ALK, проверьте и зафиксируйте его.

## Проверка одной задачи Markdown

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode review \
  --file tasks/proposal.md \
  --out work/review/proposal-start.json

agent-lifecycle review-mesh recommend \
  --file tasks/proposal.md \
  --out work/review/proposal-recommendation.json
```

Идентификатор адаптера выбирает контекст внешнего инструмента для приёма
задачи. Обычный Markdown не запускает внешний процесс или модель.

## Проверка папки плана Markdown

Если план разделён на несколько файлов, сначала импортируйте папку:

```bash
agent-lifecycle import plan \
  --source tasks/release-x/ \
  --dialect spec-kit \
  --out work/review/plan-import.json
```

Затем передайте проверяющему задачу, которая ссылается на папку или полученный
артефакт. Проверка должна охватывать требования, критерии приёмки, подтверждения,
границы записи, безопасность и заявления о готовности выпуска.

## Проверка изменений кода

Подготовьте явную задачу проверки и передайте её ALK:

```bash
mkdir -p work/code-review/current
git diff origin/main...HEAD > work/code-review/current/diff.patch

agent-lifecycle start \
  --adapter <adapter-id> \
  --mode review \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/start.json
```

Если архитектура описана, перечислите её документы в задаче. Подробные примеры
находятся в [сценариях проверки кода](code-review-workflows.md).

## Задача с учётом риска

Используйте этот маршрут только после проверки и фиксации плана. Сначала
получите профиль выполнения без изменения состояния:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode implement \
  --risk auto \
  --file tasks/my-release/plan.manifest.json \
  --state work/my-release/run.state.json \
  --lock tasks/my-release/plan.lock.json \
  --task WS-01 \
  --operation-id start-WS-01-attempt-1 \
  --expected-revision 3 \
  --source-revision <source-sha> \
  --host-model-profile profiles/hosts/host-live-profile.v1.json \
  --risk-profile-out work/my-release/WS-01/risk-profile.json
```

Затем начните попытку с тем же идентификатором операции:

```bash
agent-lifecycle workflow task-start \
  --state work/my-release/run.state.json \
  --task WS-01 \
  --operation-id start-WS-01-attempt-1 \
  --expected-revision 3 \
  --source-revision <source-sha> \
  --risk-profile work/my-release/WS-01/risk-profile.json \
  --reason "начать попытку с учётом риска"
```

Внешний инструмент должен подтвердить расход токенов, число обращений и время.
Отсутствующие, приблизительные, несвязанные или превышающие лимит значения
блокируют переход результата. Подробнее: [выполнение с учётом
риска](../reference/risk-aware-execution.md).

## Аудит подтверждений реализации

После результата задачи и независимой проверки выполните аудит реализации:

```bash
agent-lifecycle audit implementation \
  --manifest tasks/release-x/plan.manifest.json \
  --state work/run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

Параметр `--review-mesh-quorum <path>` нужен только тогда, когда зафиксированный
план требует групповой кворум на этом этапе.

Следуйте frozen последовательности валидации. После сбоя остановите её и
выясните причину до запуска проверок, которые исправление сделает неактуальными.
Сохраняйте неуспешные квитанции и все расходы. Повторно используйте успешную
проверку только при подтверждении точными байтами исходников, дайджестами входов
и зависимостями; сохраните эти байты до исправления. Передавайте аудиту
канонические артефакты полномочий, а не переформатированный JSON для отображения.
См. [Безопасное создание артефактов](../reference/safe-artifact-authoring.md).

## Новая попытка доработки

Этот сценарий применяется, когда независимая проверка или аудит реализации
возвращает `REWORK`, а исправления остаются внутри границ зафиксированной
задачи. План должен использовать `remediationMode: ask` или `bounded-auto` и
задавать `maxTaskAttempts` не меньше 2.

Перед сохранением каждого результата вычислите актуальный снимок Git:

```bash
agent-lifecycle workflow task-snapshot \
  --state work/run.state.json \
  --task WS-01 \
  --out work/WS-01/attempt-1/task-snapshot.json
```

Исполнитель помещает объект `claim` из ответа в поле `changeSet` результата
задачи. После `task-result` и независимой проверки запросите доработку с точными
идентификаторами открытых находок. Для находок task-review используйте значения
схемы `open` и `closed` в нижнем регистре; вердикт проверки остаётся `REWORK`:

```bash
agent-lifecycle workflow task-rework \
  --state work/run.state.json \
  --task WS-01 \
  --operation-id rework-WS-01-attempt-1 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --review work/WS-01/attempt-1/task-review.json \
  --finding-id F-101 \
  --reason "исправить находки независимой проверки"
```

Добавьте `--implementation-audit <path>`, если аудит обязателен по плану или
именно он вернул `REWORK`. Команда сохраняет идентификаторы артефактов без
копирования их содержимого. После этого `workflow run` снова возвращает ту же
задачу, а `task-start` открывает первый свободный номер попытки. Результат,
проверка и аудит прошлой попытки остаются неизменными.

## Использование task-local workflow v4

Для нового запуска по проверенному frozen plan вычислите инициализацию из
корня репозитория. Используйте путь состояния и package id из этого плана:

```bash
agent-lifecycle workflow init \
  --manifest tasks/release-x/plan.manifest.json \
  --state work/run.state.json \
  --run-id run-001 \
  --package-id release-x
```

Проекция ничего не записывает. Примените её с текущим полным `bindingDigest`:

```bash
agent-lifecycle workflow init \
  --manifest tasks/release-x/plan.manifest.json \
  --state work/run.state.json \
  --run-id run-001 \
  --package-id release-x \
  --apply \
  --projected-target-digest <full-binding-digest> \
  --operation-id initial-adoption
```

Составной маршрут компилирует packets в `<artifactRoot>/workflow/task-packets`,
создаёт состояние v4 и принимает план в `AWAITING_AUTHORIZATION`. Он не начинает
выполнение. Используйте отдельный существующий маршрут разрешения. Без
`--manifest` команда `workflow init` создаёт только несвязанное состояние.
Для политик, не поддержанных составным маршрутом, используйте существующий
явный маршрут compile/init/adopt. Проверки селекторов и правила отказа:
[Составная инициализация](../reference/cli.md).

Для legacy-состояния v3 используйте явную миграцию, связывая исходную
ревизию и ожидаемую ревизию состояния с квитанцией миграции:

```bash
agent-lifecycle workflow state-migrate \
  --state work/run.state.json \
  --operation-id migrate-run-001 \
  --expected-revision 1 \
  --source-revision <source-sha>
```

После результата задачи и независимого ревью применяйте единый маршрут
результата задачи. `ACCEPTED`, `REWORK`, `CONTRACT_CHANGE` и `BLOCKED` имеют
локальный статус задачи; активный сосед продолжает работу, а артефакты
предыдущей попытки остаются неизменными:

```bash
agent-lifecycle workflow task-review-apply \
  --state work/run.state.json \
  --task WS-01 \
  --operation-id review-WS-01-attempt-1 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --review work/WS-01/attempt-1/task-review.json \
  --reason "apply independent review"
```

Результат уже присоединён командой `workflow task-result`; у `task-review-apply`
нет параметра `--result`. Пример сверяется с действующим parser и `--help`.


Состояние переходит в `FINAL_AUDIT` только после принятия всех обязательных
задач. Старые команды `task-accept` и `task-rework` остаются совместимыми
обёртками на один релиз и используют тот же сервис переходов.

## Восстановление запуска без ручной записи состояния

Запуски с обязательным одобрением принимают подтверждение с точной связью
через `workflow authorize`; режим `PLAN_ONLY` никогда не становится
исполняемым. Для одного действия хоста поставьте поддерживаемый этап на паузу
через `workflow external-pause`, а возобновляйте `workflow external-resume`
только после записи соответствующего подтверждения. Типизированный блокер
содержит разрешённый маршрут, поэтому общая команда `resolve-blocker` не может
снять блокер задачи или плана.

После принятия обязательных задач применяйте решение независимого финального
аудита явно:

```bash
agent-lifecycle workflow final-audit-outcome \
  --state work/run.state.json \
  --operation-id final-audit-outcome-1 \
  --expected-revision 12 \
  --source-revision <source-sha> \
  --final-audit final/final-audit.json \
  --verdict REWORK \
  --task-id WS-01 \
  --finding-id F-001 \
  --reason "исправить независимую находку"
```

`ACCEPTED` продолжает существующие гейты финализации. `REWORK` архивирует
названные принятые попытки и сохраняет их файлы, `CONTRACT_CHANGE` требует
новый зафиксированный план, а `BLOCKED` ждёт объявленное внешнее действие. Ни
один из этих переходов не меняет зафиксированный план и не увеличивает
бюджет повторов.

## Цель и прогресс

```bash
agent-lifecycle goal view \
  --record work/run/goal.json \
  --state work/run/state.json \
  --usage-receipt work/run/usage.json \
  --change-summary work/run/change-summary.json \
  --terminal
```

Команда не заявляет о завершении. Она только объединяет цель, состояние,
прогресс, расход и сводку изменений.

## Исправление с Bug Forensics

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode plan \
  --file work/bugs/checkout-regression.md \
  --out work/bugs/checkout-start.json
```

Рекомендация сама по себе не включает обязательные проверки. Зафиксированный
план должен явно потребовать воспроизведение, отпечаток ошибки, журнал гипотез,
регрессионное подтверждение и оценку влияния. Подробнее: [сценарии Bug
Forensics](bug-forensics-workflows.md).

## Групповая проверка

Для задач с повышенным риском подготовьте назначения через `review-mesh
assign`, запустите проверяющих вне ALK, импортируйте их структурированные
ответы, затем объедините находки и проверьте кворум. Поддерживаются любые
доступные связки адаптеров и моделей. Подробнее: [групповая
проверка](../reference/review-mesh.md).

## Правила безопасности

- Не сохраняйте секреты и значения частного окружения в файлах задач.
- Для переносимых пакетов используйте относительные пути репозитория.
- Считайте `review-mesh recommend` рекомендацией, пока план явно не требует
  групповую проверку.
- Установка плагина не доказывает прохождение рабочего цикла ALK.
- Обычный текст, Markdown и импортированный план сами по себе не разрешают
  реализацию.

Для обычного маршрута используйте `agent-lifecycle start`. Низкоуровневые
команды `adapter task start`, `adapter run` и `adapter session resume` нужны
только автоматизации, которой требуется прямое управление отдельным шагом.


### Ограниченные примеры подготовки и доказательств

- После поправки проверенного плана скомпилируйте новый индекс пакетов в новом
  корне артефактов до adoption. Новый путь результата не заменяет старый индекс.
  Сохраните прежние пакеты, отказы и расходы.
- Связывайте текст приёмки с каноническим требованием. После изменения объёма
  обновите связанную приёмку до freeze. Структурная проверка не доказывает
  смысловое совпадение скопированного текста.
- До обещания неизменного AST тестов и чистого lint всего файла проверьте
  действующие селекторы. Baseline продуктового кода не освобождает тесты.
  Не создавайте baseline или ignore задним числом после отказа.
- Для долгих проверок сохраняйте имена выбранных тестов, начало и исход.
  Используйте имеющийся ограниченный сборщик или подробный вывод того же набора.
  Частичный журнал не доказывает успех отсутствующих тестов.
- Разделяйте процессы, проверки, измерения и расход провайдера. Учитывайте одну
  реальную квитанцию один раз, даже при ссылках контроллера и исполнителя.
  Сохраняйте UNKNOWN и исходные часы после повторов и compact.
- Частичный профиль может обосновать ограниченный эксперимент, но не ускорение
  всего набора. До явного решения сохраняйте замороженную цель. Новый контроль
  в том же CI job требует собственного конечного бюджета и срока.
- Если вспомогательный процесс упал до нагрузки, сохраните это различие.
  Отчёт об ошибке внешнего проекта — гипотеза, а не доказанная местная причина.
  Фиксируйте точные байты платформы и явную материализацию CRLF; не нормализуйте
  проваленное доказательство молча и не переименовывайте его в `PASS`.

Это примеры существующих правил по Release 2.28. Они не добавляют раунд аудита
или переход native workflow.

## Достижимость возможности до freeze

До freeze свяжите новый маршрут, переносимость или изменение поддерживаемого
сценария с 1–3 реальными точками входа, нижней границей возможностей/полномочий,
существующим отрицательным тестом и точными владельцами изменений. Различайте
рефакторинг и новую возможность: UNIT_ONLY/mock не заменяет сквозной сценарий.
Если нижний слой намеренно отказывает, получите решение пользователя до freeze:
сузить обещание либо включить изменения нижнего слоя и его владельцев. Если
1–3 точек недостаточно, выделите ограниченный feasibility probe. Проверка входит
в существующее plan review; новый общий аудит, schema и обязательный receipt
не вводятся. Структурные plan verify/ownership/traceability не доказывают
семантическую достижимость.

Пример WS-03 релиза 2.24: `resolve_declared_ledger_context` сохраняет
`declared-ledger-route-unsupported` и тест
`test_unsupported_package_and_rebound_opening_refuse`. Переносимый fixture
типизированного интерфейса остаётся UNIT_ONLY. Изоляция legacy-путей —
рефакторинг; generic финансовый маршрут и новая квалификация хоста потребовали
бы отдельной области изменений и сквозного доказательства.
