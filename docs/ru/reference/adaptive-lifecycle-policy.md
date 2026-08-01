# Adaptive lifecycle policy

Adaptive lifecycle policy выбирает самый лёгкий безопасный режим жизненного
цикла по нейтральным входам задачи. Цель — сохранить качество решения и не
тратить лишние токены/время на процесс там, где это не нужно.

Используются только portable inputs:

- task shape;
- SDD tier;
- risk flags;
- required evidence;
- число прошлых попыток;
- размер контекста в токенах;
- resource caps для вызовов, wall time и billable tokens.

Provider names, concrete model names, API keys и auth details не попадают в
portable policy request или decision. Выбор конкретной модели остаётся
host-local задачей адаптера.

## Quality floor

`agent-lifecycle-quality-floor-decision.v1` фиксирует минимальный режим, ниже
которого нельзя опускаться. Security/S2 work требует минимум `strict`,
release-proof и production-promotion требуют `release`.

## Команды

```bash
agent-lifecycle policy adaptive-decision \
  --request <adaptive-request.json> \
  --baseline-profile profiles/lifecycle-baselines.v1.json \
  --out <adaptive-decision.json>

agent-lifecycle policy adaptive-check --decision <adaptive-decision.json>
```

По умолчанию decision остаётся advisory. Автоматический выбор разрешён только
при `automaticSelectionEnabled: true`, отсутствии blockers и режиме не ниже
quality floor.
Decision receipt использует `agent-adaptive-lifecycle-policy-decision.v1`.

## Расход

Решение использует `resourceBasis: "tokens-and-resources"` и всегда оставляет
`monetaryFieldsUsed: false`. Monetary metadata допустима только для
`budgetMode: "metered"` и не участвует в выборе режима.
