# Передача между фазами и сессиями

Длинная работа по жизненному циклу должна переходить между сессиями через
ограниченные артефакты ALK, а не через вставку полной переписки в контекст
следующей модели. Рецепт использует существующие команды и не создаёт второе
хранилище сессий или новый путь полномочий.

## Однократная подготовка

Храните проверенный manifest, lock, состояние workflow и скомпилированные
пакеты задач в объявленных местах. Создайте компактные артефакты плана:

```bash
agent-lifecycle plan snapshot \
  --manifest work/plans/release/plan.manifest.json \
  --out work/release/plan-snapshot.json

agent-lifecycle plan handoff \
  --manifest work/plans/release/plan.manifest.json \
  --snapshot work/release/plan-snapshot.json \
  --lock work/plans/release/plan.lock.json \
  --phase-packet-out work/release/planning-phase-packet.json \
  --max-workstreams 12 \
  --target-tokens 4096 \
  --out work/release/plan-handoff.json
```

Это подготовительные команды оператора. Они не фиксируют план, не авторизуют
выполнение и не принимают задачу.

## Сессия планирования

Передайте сессии запрос пользователя, ссылки на репозитории и текущий пакет
плана. Ограниченный результат - manifest, review, lock, snapshot и handoff. Не
переносите дальше полный transcript.

Перед завершением запишите в checkpoint-input только структурированные факты:
последний intent, принятые решения, открытые блокеры, следующий обязательный
шаг и ссылки на артефакты с digest. Затем выполните:

```bash
agent-lifecycle context checkpoint \
  --session planning-session \
  --state work/release/run.state.json \
  --plan work/plans/release/plan.manifest.json \
  --input work/release/planning-checkpoint-input.json \
  --reason planning-complete \
  --capture-mode MILESTONE \
  --adapter <adapter-id> \
  --out work/release/planning-checkpoint-receipt.json
```

## Сессия реализации

Начинайте с текущего состояния workflow и одного выбранного task packet.
При необходимости восстановите ограниченное продолжение:

```bash
agent-lifecycle context restore \
  --checkpoint .alk/context/checkpoints/<checkpoint-id>.json \
  --state work/release/run.state.json \
  --session planning-session \
  --target-tokens 2048 \
  --out work/release/planning-continuation.json
```

Продолжение содержит `implementationAuthorized: false` и `proofAuthority:
none`. Оператор всё равно обязан выполнить текущий переход с полномочиями,
например `workflow task-start`, с ожидаемой ревизией состояния и source
revision. Исполнитель читает свой пакет, меняет только принадлежащие ему пути,
создаёт свежий `workflow task-snapshot` и отправляет `workflow task-result`.

Новая сессия может получить отдельный ограниченный пакет реализации без
изменения обычного task change set:

```bash
agent-lifecycle workflow task-snapshot \
  --state work/release/run.state.json \
  --task WS-01 \
  --manifest work/plans/release/plan.manifest.json \
  --lock work/plans/release/plan.lock.json \
  --phase-packet-purpose IMPLEMENTATION \
  --phase-packet-out work/release/WS-01/implementation-phase-packet.json \
  --out work/release/WS-01/task-change-set.json
```

## Независимая сессия аудита

Рецензенту нужны зафиксированные manifest и lock, task packet, свежий change
set, task result и evidence конкретных критериев. Не передавайте скрытые
рассуждения исполнителя и не просите вывести приёмку из текстового резюме.
Review содержит отдельную идентичность рецензента и его run id.

После `task-result` повторите `workflow task-snapshot` с
`--phase-packet-purpose TASK_AUDIT`: ALK спроецирует неизменяемый change set,
связанный с сохранённым результатом. Для начатой повторной попытки используйте
`REMEDIATION`; пакет содержит digest прошлых receipts, ID открытых находок и
оставшееся число попыток.

`workflow task-review-apply`, `workflow task-accept` и `workflow task-rework` -
переходы с полномочиями. Оператор вызывает их только с действительным
независимым review, связанным с текущей попыткой и source revision.

## Сессия приёмки

Сессии приёмки нужны текущее состояние workflow, принятый review, подтверждения
финального аудита и компактный статус, а не прошлые полные переписки. Для
длинной цели оператор может запросить ограниченное представление:

```bash
agent-lifecycle goal summarize \
  --record work/goal-record.json \
  --state work/goal-state.json \
  --target-window 2048
```

Завершайте работу через действующие команды финального аудита и финализации.
Checkpoint, snapshot, handoff и summary остаются только evidence и не заменяют
lock, review задачи, авторизацию или final proof.

## Обязательные границы

- Соблюдайте лимиты пакета, checkpoint и handoff из зафиксированного плана.
- Отклоняйте устаревшие plan, state, source revision и lineage попытки.
- При REWORK сохраняйте прошлые result и review неизменными.
- Не сохраняйте raw transcript, system prompt, секреты и локальные абсолютные пути.
- Отмечайте отсутствующую телеметрию как unavailable, а не как ноль.
- Не снижайте review, security, architecture или quality gates ради контекста.
