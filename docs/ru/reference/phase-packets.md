# Пакеты фаз

Пакеты фаз - ограниченные проекции фактов для конкретной цели, которые
передаются между сессиями моделей. Они уменьшают повторную загрузку контекста,
не создавая второе состояние workflow или второй путь полномочий.

Схема конверта - `agent-phase-packet.v1`. Допустимы четыре назначения:

- `PLANNING_HANDOFF` для выбранных потоков работ и их зависимостей;
- `IMPLEMENTATION` для одной попытки задачи, области, критериев и evidence;
- `TASK_AUDIT` для сохранённого результата, неизменяемого change set и review;
- `REMEDIATION` для прошлого result/review, открытых находок и бюджета повторов.

Пакет связан с текущими plan, lock, source revision и соответствующей ревизией
состояния. Отдельные digest связывают область записи, критерии приёмки,
evidence и активные блокеры. Размер конверта ограничен 64 КиБ; обязательные
факты не удаляются ради соблюдения лимита.

## Создание пакетов

`plan handoff` сохраняет прежний результат, а необязательный пакет пишет в
отдельный файл:

```bash
agent-lifecycle plan handoff \
  --manifest <plan.manifest.json> \
  --snapshot <plan-snapshot.json> \
  --lock <plan.lock.json> \
  --phase-packet-out <planning-phase-packet.json> \
  --out <plan-handoff.json>
```

Пакет задачи создаётся как дополнительный результат read-only снимка:

```bash
agent-lifecycle workflow task-snapshot \
  --state <run.state.json> \
  --task <task-id> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --phase-packet-purpose IMPLEMENTATION \
  --phase-packet-out <implementation-phase-packet.json> \
  --out <task-change-set.json>
```

Четыре параметра пакета у `task-snapshot` задаются только вместе. Используйте
`TASK_AUDIT` после сохранения результата и `REMEDIATION` для начатой повторной
попытки. Без новых параметров JSON прежних handoff и task change set не
меняется.

## Граница безопасности

Payload закрыт и рекурсивно запрещает переписки, промпты, учётные данные,
cookie, секреты и поля полномочий. Строки проходят существующую редакцию
секретов и локальных путей. Ошибки имеют стабильные коды:

- `phase-packet-required-fact-missing`;
- `phase-packet-forbidden-content`;
- `phase-packet-context-limit-exceeded`.

Каждый конверт содержит `implementationAuthorized: false`, `proofAuthority: none`
и `productionPromotionClaimed: false`. Пакет не запускает работу, не
принимает задачу, не фиксирует план, не заменяет review и не продвигает релиз.
Полномочия остаются у текущих lock, workflow state и обычных переходов ALK.
