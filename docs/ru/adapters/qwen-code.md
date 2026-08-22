# Адаптер Qwen Code

Проекция Qwen Code имеет уровень поддержки `VERIFIED` для Qwen Code `0.21.0`
на проверенной локальной связке провайдера и модели. Описание относится к этой
точной интеграции исходного дерева.

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
`managedLaunch.status` имеет значение `WRAPPER_ONLY`; проверенный локальный
профиль задаёт маршрут принятого запуска зафиксированной задачи.

Уровень поддержки адаптера и состояние нового нормализатора токенов учитываются
раздельно. Адаптер имеет статус `VERIFIED`, а
`usageNormalization.status: FIXTURE_ONLY` сохраняет новые подтверждения в
состоянии `ESTIMATED` до отдельной проверки нормализатора на реальном диапазоне
версий хоста. Подробнее:
[локальный учёт токенов хоста](../reference/host-local-token-accounting.md).

## Запуск только для планирования

Точная версия профиля: `0.21.8`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Порядок
квалификации включает встроенный режим только для чтения или запрета
инструментов.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter qwen-code --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/qwen-code.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/qwen-code.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/qwen-code.json
```

Маршрут планирования использует статус и подтверждения из раздела [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Статус контроля жизненного цикла

Для адаптера Qwen Code каждая операция дескриптора (`cancel`, `discover`, `final-audit`, `install`, `launch`, `model-route-execution`, `result-collection`, `resume`, `task-audit`, `tool-execution`, `adapter-event-stream`, `usage-attestation`, `validate-envelope`, `wait`) публикует
`declaredLevel: GUIDANCE_ONLY`, `supportedLevel: GUIDANCE_ONLY`,
`qualifiedLevel: GUIDANCE_ONLY` и `qualificationStatus: NO_RECOMMENDATION`.
Статус управляемого запуска - `WRAPPER_ONLY`. Это значения контроля жизненного
цикла для отдельных операций, а не общий уровень поддержки адаптера в матрице.

Страница и навык адаптера объясняют порядок работы ALK внутри хоста. Они не
заявляют, что промпт, плагин или обёртка блокируют действие. Позже для отдельных
операций можно квалифицировать производителя хоста для точной версии, но
одних офлайн-фикстур для повышения уровня недостаточно. См. [необязательный
контроль жизненного цикла](lifecycle-control.md) и [использование ALK с
адаптером](usage-modes.md).

## Использование ALK в Qwen Code

Документированный маршрут Qwen Code — команда в терминале. Через отдельно
проверенную конфигурацию Qwen Code можно подключить общие навыки:

```bash
agent-lifecycle start --adapter qwen-code --file task.md
```

Команда создаёт входные артефакты ALK. Для работы хоста используйте маршрут
запуска через проверенный профиль. Подробнее: [использование ALK с
адаптером](usage-modes.md).
