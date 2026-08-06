# Непрерывность цели

`agent-goal-record.v1` — дополнительный артефакт для длинных задач. Он хранит
исходное намерение пользователя, ожидаемый результат, ограничения,
идентификаторы подтверждений и привязку к workflow, чтобы продолжить работу без
пересказа длинной истории чата.

Это не второе состояние workflow. Фаза, статусы задач, блокеры и финализация
по-прежнему берутся из состояния workflow. Запись цели действительна только при
совпадении привязки с текущим состоянием.

```bash
agent-lifecycle goal check \
  --record <goal-record.json> \
  --state <run.state.json> \
  --current

agent-lifecycle goal summarize \
  --record <goal-record.json> \
  --state <run.state.json> \
  --profile profiles/small-context-profile.v1.json \
  --target-window 8k

agent-lifecycle goal view \
  --record <goal-record.json> \
  --state <run.state.json> \
  --usage-receipt <usage.json> \
  --change-summary <changes.json>

agent-lifecycle goal update \
  --record <goal-record.json> \
  --state <run.state.json> \
  --status READY_FOR_FINALIZATION \
  --evidence-id <evidence-id> \
  --reason "<reason>" \
  --out <goal-record.updated.json>
```

`goal summarize` создаёт `agent-objective-snapshot.v1`: краткий снимок цели,
ограничений, отпечатков, подтверждений и следующего действия. Он помогает
маленьким моделям продолжать работу, но не снижает требования к аудиту и
финальному подтверждению.

## Цель и прогресс

`goal view` создаёт `agent-goal-progress-view.v1`: краткое представление цели,
текущей фазы, следующего действия, статусов задач, прогресса, подтверждённого
расхода токенов и счётчика изменений.

JSON удобно передавать другим инструментам:

```bash
agent-lifecycle goal view \
  --record <goal-record.json> \
  --state <run.state.json> \
  --usage-receipt <usage.json> \
  --change-summary <changes.json> \
  --out work/run/goal-progress-view.json
```

Для чтения в терминале используйте явный флаг:

```bash
agent-lifecycle goal view \
  --record <goal-record.json> \
  --state <run.state.json> \
  --terminal
```

Команда только читает артефакты: не меняет состояние рабочего цикла, не
перезаписывает запись цели, не запускает CLI-хосты и не вызывает модель. Если
расход токенов не подтверждён, он показывается как `↑?/↓? tok`.
