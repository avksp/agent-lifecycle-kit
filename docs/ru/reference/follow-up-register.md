# Реестр отложенной работы

Реестр отложенной работы фиксирует задачи, которые явно вынесены за текущий
объём, заблокированы внешним действием или запланированы после принятого
компромисса. Сам по себе реестр не является подтверждением приёмки.

Каждый пункт `agent-follow-up-register.v1` содержит источник, владельца, статус,
целевой релиз или блокер, требования к закрытию и влияние на текущий объём.
Открытые пункты с влиянием `current-acceptance` или `completion-proof` блокируют
финализацию.

```bash
agent-lifecycle followup check \
  --register <follow-up-register.json> \
  --state <run.state.json> \
  --fail-on-finalization-blockers

agent-lifecycle followup add \
  --register <follow-up-register.json> \
  --item <follow-up-item.json>

agent-lifecycle followup close \
  --register <follow-up-register.json> \
  --item-id <id> \
  --evidence-id <evidence-id> \
  --artifact <path> \
  --verifier <id> \
  --reason "<reason>"
```

`agent-follow-up-summary.v1` — компактная сводка для продолжения работы в
маленьком контексте. Она показывает счётчики, открытые пункты и финальные
блокеры, но не заменяет полный реестр.
