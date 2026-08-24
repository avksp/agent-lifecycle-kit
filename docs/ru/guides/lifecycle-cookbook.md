# Сценарии задач жизненного цикла

Используйте эти сценарии, когда задача понятна, но собирать последовательность
низкоуровневых команд ALK вручную не требуется. Обычный текст остаётся
черновиком, пока проверенный план или связанный запрос запуска явно не разрешит
выполнение.

## Выбор сценария

| Задача | Раздел | Останавливается до реализации |
| --- | --- | --- |
| Исследовать область и подготовить план | [Только исследование и планирование](#только-исследование-и-планирование) | Да |
| Проверить один Markdown-файл | [Проверка одной задачи Markdown](#проверка-одной-задачи-markdown) | Да |
| Проверить папку плана | [Проверка папки плана Markdown](#проверка-папки-плана-markdown) | Да |
| Проверить код или PR/MR | [Проверка изменений кода](#проверка-изменений-кода) | Да |
| Проверить выполненную работу ALK | [Аудит подтверждений реализации](#аудит-подтверждений-реализации) | Нет, проверяется готовая работа |
| Продолжить после решения о доработке | [Новая попытка доработки](#новая-попытка-доработки) | Нет, продолжается зафиксированная задача |
| Найти или исправить ошибку | [Исправление с Bug Forensics](#исправление-с-bug-forensics) | Нет, после разрешения зафиксированного плана |
| Привлечь нескольких проверяющих | [Групповая проверка](#групповая-проверка) | Да, если план не требует кворум |
| Посмотреть состояние запуска | [Цель и прогресс](#цель-и-прогресс) | Да |
| Запустить задачу с ограничениями ресурсов | [Задача с учётом риска](#задача-с-учётом-риска) | Нет, разрешается одна попытка |

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
идентификаторами открытых находок:

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

Для нового запуска сначала создайте проверенное состояние v4:

```bash
agent-lifecycle workflow init \
  --state work/run.state.json \
  --run-id run-001 \
  --package-id release-x
```

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
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json
```

Состояние переходит в `FINAL_AUDIT` только после принятия всех обязательных
задач. Старые команды `task-accept` и `task-rework` остаются совместимыми
обёртками на один релиз и используют тот же сервис переходов.

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
