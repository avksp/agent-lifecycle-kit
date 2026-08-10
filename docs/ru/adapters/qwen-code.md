# Адаптер Qwen Code

Проекция Qwen Code имеет статус `VERIFIED` для Qwen Code `0.21.0` на
проверенной локальной связке провайдера и модели. Это совместимость исходного
дерева для конкретного хоста, а не одобрение публичного пакета, каталога или
промышленная готовность.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/qwen-code/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/qwen-code/adapter.descriptor.json \
  --skip-host-commands
```

Принятое подтверждение реального запуска от 2026-07-29 включает:

- Qwen Code `0.21.0`;
- локальную обезличенную связку провайдера и модели;
- 13/13 операций базовой проверки хоста;
- 14/14 запусков калибровки;
- 0 регрессий качества;
- финальное подтверждение жизненного цикла.

Резюме: `docs/adapters/evidence/qwen-code-host-local-live-2026-07-29.md`.
Историческая заметка о каркасе и дымовой проверке:
`docs/adapters/evidence/qwen-code-0.11.0.md`.
Прямой безопасный запуск CLI хоста из ядра не заявляется:
`managedLaunch.status` остаётся `WRAPPER_ONLY`.

Зрелость адаптера и состояние нового нормализатора токенов учитываются
раздельно. Адаптер остаётся `VERIFIED`, а
`usageNormalization.status: FIXTURE_ONLY` сохраняет новые подтверждения в
состоянии `ESTIMATED` до отдельной проверки нормализатора на реальном диапазоне
версий хоста. Подробнее:
[локальный учёт токенов хоста](../reference/host-local-token-accounting.md).

## Запуск только для планирования

Точная версия профиля: `0.21.8`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Для этого контракта не подтверждён встроенный режим только для чтения или запрета инструментов.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter qwen-code --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/qwen-code.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/qwen-code.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/qwen-code.json
```

Успешная проверка версии не разрешает запуск планирования.
`managedLaunch.status` остаётся `WRAPPER_ONLY`, а зрелость адаптера не повышает
состояние поддержки планирования. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).
