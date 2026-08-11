# Адаптер Kimi Code

Проекция Kimi Code является `EXPERIMENTAL`. В ней есть ограниченный
контролируемый запуск и обвязка реального хоста, но нет `VERIFIED`,
промышленной готовности или переносимых имён провайдера и модели.

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

Текущая причина блокировки: `BLOCKED_HOST_MODEL_NOT_CONFIGURED`. Пока провайдер
и алиас модели не настроены, подтверждение реального запуска, калибровку и
финальное подтверждение получить нельзя.

Локальный нормализатор `stream-json` имеет состояние `FIXTURE_ONLY`.
Исполнитель и испытательный стенд используют один ограниченный разбор, но его
результат не подходит для S1/S2. Подробнее:
[локальный учёт токенов хоста](../reference/host-local-token-accounting.md).

## Запуск только для планирования

Точная версия профиля: `0.30.0`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Внешний инструмент пока не имеет подтверждённой ограниченной передачи результата через стандартный ввод.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter kimi-code --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/kimi-code.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/kimi-code.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/kimi-code.json
```

Успешная проверка версии не разрешает запуск планирования.
`managedLaunch.status` остаётся `WRAPPER_ONLY`, а зрелость адаптера не повышает
состояние поддержки планирования. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Использование ALK в Kimi Code

Kimi Code позволяет выбрать каталог навыков, но встроенный адаптер не
устанавливает навыки ALK. Подключите общий каталог `skills/` из отмеченной
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

Без явной настройки навыков основным является запуск через команду. По
умолчанию она не запускает Kimi Code. Подробнее: [использование ALK с
адаптером](usage-modes.md).
