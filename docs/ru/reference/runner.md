# Контролируемый запуск

Runner — нейтральный контроллер цикла попыток. Он записывает узкое состояние
для попыток задачи, проверок, ревью, исправлений, смены маршрута, разделения,
блокировок, остановки и возобновления.

Runner не заменяет состояние workflow. Workflow остаётся источником правды для
фазы, приёмки задач, блокеров и финального подтверждения.

```bash
agent-lifecycle runner start \
  --state <run.state.json> \
  --runner <runner.state.json> \
  --operation-id <id> \
  --reason "<reason>"

agent-lifecycle runner status \
  --runner <runner.state.json> \
  --state <run.state.json>

agent-lifecycle runner transition \
  --runner <runner.state.json> \
  --state <run.state.json> \
  --request <runner-transition-request.json>

agent-lifecycle runner stop \
  --runner <runner.state.json> \
  --state <run.state.json> \
  --operation-id <id> \
  --expected-runner-revision <n> \
  --reason "<reason>"

agent-lifecycle runner resume \
  --runner <runner.state.json> \
  --state <run.state.json> \
  --operation-id <id> \
  --expected-runner-revision <n> \
  --reason "<reason>"
```

Переходы описываются `agent-runner-transition-request.v1`. Поддерживаются
`attempt`, `validate`, `review`, `accept`, `remediate`, `reroute`, `split`,
`block` и `abort`.

Политика `agent-runner-policy.v1` ограничивает попытки, смены маршрута,
разделения и расход токенов. Если переход превысит лимит, состояние не
записывается.
