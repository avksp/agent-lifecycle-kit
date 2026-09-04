# Предложения правил жизненного цикла

Предложения правил помогают снизить лишние шаги жизненного цикла только тогда,
когда накопленные данные достаточно надёжны и минимальный уровень качества не
снижается.

Создать предложение без записи:

```bash
agent-lifecycle policy tune --report <lifecycle-recommendation.json>
```

Записать новый артефакт можно только явно:

```bash
agent-lifecycle policy tune \
  --report <lifecycle-recommendation.json> \
  --apply \
  --output <tuned-policy.json>
```

Команда не меняет существующие файлы правил. Она создаёт
`agent-lifecycle-tuned-policy.v1` с предлагаемыми изменениями, откатом,
отпечатком источника и сохранёнными ограничениями качества.

Регрессии могут заблокировать применение:

```bash
agent-lifecycle policy tune \
  --report <lifecycle-recommendation.json> \
  --regression-signal <regression-signal.json>
```

Для задач безопасности, релиза, контрактов, адаптеров, миграций, архитектуры и
S2 правила могут сохранять или повышать режим жизненного цикла, но не удалять
обязательные подтверждения, проверку или финальное доказательство.

## Принятие стратегии выполнения

`agent-execution-strategy.v1` объединяет существующие решения по риску,
качеству, маршруту, пакету и проверке для одной точной следующей попытки задачи.
Управляемый `start`, прямой `workflow task-start` и `workflow continue` могут
принять артефакт только при `automaticAdoptionEligible: true` и возможности
заново проверить каждую связь с планом, lock-файлом, состоянием, исходной
ревизией, дескриптором, возможностями и профилем проекта. Вычисление не запускает
модель и не даёт полномочий workflow.

Явные настройки оператора или проекта могут сохранить либо усилить
зафиксированную нижнюю границу, но не понизить её. Отсутствующее подтверждение
возможностей не разрешает ослабить маршрут. Проверка задачи по текущему снимку
остаётся независимой, а финальная `RELEASE_FULL` обязательна.

## Подтверждения правил запуска

`agent-runtime-policy-receipt.v1` фиксирует решение адаптера: `ALLOW`, `DENY`
или `ASK`.

```bash
agent-lifecycle policy runtime-receipt \
  --policy-id <policy-id> \
  --action DENY \
  --subject <subject.json> \
  --adapter-evidence <adapter-evidence.json> \
  --enforcement-mode enforced \
  --out <runtime-policy-receipt.json>

agent-lifecycle policy runtime-check \
  --receipt <runtime-policy-receipt.json>
```

`enforcementMode: enforced` проходит только при доказанном предварительном
ограничении до выполнения. Запись после факта должна использовать
`enforcementMode: advisory`.
