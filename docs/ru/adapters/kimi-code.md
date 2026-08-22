# Адаптер Kimi Code

Проекция Kimi Code имеет уровень поддержки `EXPERIMENTAL`. В неё входят
ограниченный контролируемый запуск и обвязка реального хоста; имена провайдера
и модели задаются локально в настройках хоста.

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/kimi-code/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/kimi-code/adapter.descriptor.json \
  --skip-host-commands

python tools/live_hosts/kimi_code_harness.py \
  --mode fixture-check \
  --baseline conformance/core/adapter-baseline.v1.json \
  --report <kimi-code-fixture-check.json>
```

Kimi Code `0.30.0` прошёл безопасный локальный осмотр версии, справки,
headless-режима, потокового JSON, выбора модели, режимов прав, каталога skills,
провайдеров, экспорта сессии и ACP stdio discovery. Резюме:
`docs/adapters/evidence/kimi-code-0.12.0.md`.

Текущая квалификационная стадия: `BLOCKED_HOST_MODEL_NOT_CONFIGURED`. Настройте
провайдер и алиас модели, чтобы получить подтверждения реального запуска,
калибровки и жизненного цикла.

Локальный нормализатор `stream-json` имеет состояние `FIXTURE_ONLY`.
Исполнитель и испытательный стенд используют один ограниченный разбор, но его
для квалификации S1/S2 используется подтверждение хоста. Подробнее:
[локальный учёт токенов хоста](../reference/host-local-token-accounting.md).

## Запуск только для планирования

Точная версия профиля: `0.30.0`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Порядок
квалификации использует ограниченную передачу результата через стандартный ввод.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter kimi-code --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/kimi-code.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/kimi-code.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/kimi-code.json
```

Маршрут планирования использует статус и подтверждения из раздела [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Статус контроля жизненного цикла

Для адаптера Kimi Code каждая операция дескриптора (`cancel`, `discover`, `final-audit`, `install`, `launch`, `model-route-execution`, `result-collection`, `resume`, `task-audit`, `tool-execution`, `adapter-event-stream`, `usage-attestation`, `validate-envelope`, `wait`) публикует
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

## Использование ALK в Kimi Code

Kimi Code позволяет выбрать каталог навыков. Подключите общий каталог `skills/` из отмеченной
версии через настройки внешнего инструмента и запросите
`agent-workflow-orchestrator` либо используйте:

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи полный цикл ALK: проверенное планирование, фиксацию плана, аудит
результатов реализации и принятое итоговое доказательство.
Задача: <опиши задачу или укажи Markdown-файл>
```

Этот запрос применим только после настройки навыков во внешнем инструменте.

```bash
agent-lifecycle start --adapter kimi-code --file task.md
```

Команда создаёт входные артефакты ALK. Для работы хоста используйте маршрут
запуска через проверенный профиль. Подробнее: [использование ALK с
адаптером](usage-modes.md).
