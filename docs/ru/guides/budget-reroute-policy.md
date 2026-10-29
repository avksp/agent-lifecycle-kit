# Политика перенаправления при превышении бюджета

Budget caps — защитные ограничения, а не критерии завершения задачи. Если model-backed attempt превышает route, token, wall-clock, invocation или metered spend cap, workflow должен оставить задачу незавершённой и записать budget decision до нового model invocation.

## Режимы

`agent-lifecycle-budget-exceeded-policy.v1` поддерживает:

- `manual`: пауза в `WAITING_FOR_BUDGET_DECISION` с разрешёнными operator actions;
- `auto`: детерминированный выбор одного bounded action из policy.

Для учёта ресурсов доступны:

- `metered`: требуется положительный `budgetCapUsd`; optional `meteredAskThreshold` только advisory и должен быть ниже hard cap;
- `subscription`: требуется `maxInvocations` и хотя бы один из `maxBillableTokens` или `maxWallSeconds`;
- `local`: те же resource caps, что у `subscription`, но USD cap не требуется.

`meteredAskThreshold` допустим только в `budgetModes.metered`. Subscription и local используют tokens, invocations и wall-clock caps; они не должны наследовать денежные thresholds.

## Ручная пауза

```bash
agent-lifecycle workflow budget-decision \
  --state work/<run>/workflow/run.state.json \
  --task WS-01 \
  --operation-id budget-decision-WS-01-attempt-1 \
  --expected-revision 7 \
  --source-revision <git-sha> \
  --model-usage-receipt work/WS-01/attempt-1/model-usage-receipt.json \
  --budget-policy policies/budget-exceeded-policy.json \
  --receipt work/WS-01/attempt-1/budget-decision.json \
  --reason "route token cap exceeded"
```

Команда записывает `agent-lifecycle-budget-decision-receipt.v1`, переводит run в `WAITING_FOR_BUDGET_DECISION` и устанавливает `blocker.code` в `BUDGET_DECISION_REQUIRED`.

## Применение решения

```bash
agent-lifecycle workflow budget-decision \
  --state work/<run>/workflow/run.state.json \
  --task WS-01 \
  --operation-id budget-apply-WS-01-attempt-1 \
  --expected-revision 8 \
  --source-revision <git-sha> \
  --action reroute-stronger \
  --decision-receipt work/WS-01/attempt-1/budget-decision.json \
  --route-decision work/WS-01/attempt-1/reroute-decision.json \
  --receipt work/WS-01/attempt-1/budget-decision-applied.json \
  --operator-identity-hash <redacted-operator-hash> \
  --reason "operator selected stronger route"
```

Applied receipt — второй immutable artifact `agent-lifecycle-budget-decision-receipt.v1`. Он связывает pending decision receipt, выбранное действие, operator identity для manual mode и next route decision, split packet identity или явные cap deltas.

## Критические reviews

Critical review phases не должны автоматически понижать маршрут до `budget` или `local-compact`. Если `forbidDowngradeForCriticalReview` равен true, а default auto action выбирает более дешёвый маршрут, controller выбирает stronger route, split task, продолжение того же route или abort согласно allowed actions.

## Локальная конфигурация

Конкретные provider names, subscription tiers, local model names и personal limits хранятся в host-local policy files или live evidence. Portable plans и workflow state должны содержать neutral actions, redacted model hashes и policy digests.
