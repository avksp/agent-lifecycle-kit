# Полнота плана

Проверка полноты плана — это структурный gate перед независимым аудитом. Он
проверяет, хватает ли выбранному SDD tier минимальных полномочий для безопасного
выполнения. Проверка не оценивает длину текста и не заменяет независимый аудит
плана.

## Команды

```bash
agent-lifecycle plan completeness-check \
  --manifest tasks/release-x/plan.manifest.json \
  --profile profiles/plan-completeness-profile.v1.json \
  --out work/plan-completeness.json

agent-lifecycle plan check \
  --manifest tasks/release-x/plan.manifest.json \
  --require-completeness
```

`plan completeness-check` возвращает
`agent-plan-completeness-validation.v1`. Команда может вернуть `status: FAIL`
с конкретными blockers и всё равно напечатать JSON. `plan check
--require-completeness` — режим принудительной проверки: при неполном выбранном
tier он падает с `plan-completeness-failed`.

## Профили tier

Профиль по умолчанию находится в
`profiles/plan-completeness-profile.v1.json` и использует
`agent-plan-completeness-profile.v1`.

- `S0`: один ограниченный механический workstream, точная область записи и хотя
  бы одна команда проверки.
- `S1`: требования, критерии приёмки, маршрут подтверждений, владение путями
  записи, проверка и граница влияния на релиз.
- `S2`: требования, критерии приёмки, маршрут подтверждений, владение путями
  записи, DAG, политика бюджета токенов и ресурсов, границы контекста, gates
  безопасности/релиза и финальные gates аудита.

Типовые коды blockers:

- `missing-evidence-route`
- `missing-write-ownership`
- `missing-budget-policy`
- `missing-context-limits`
- `missing-security-gate`
- `s2-final-audit-gate-missing`

## Маленькие модели

Маленькие и локальные модели должны получать компактные планы, но компактность
не означает недостаток структуры. Из пакета можно убрать лишний фон, если
остаются активная задача, область записи, критерии приёмки, маршрут
подтверждений, команда проверки и контракт результата.
