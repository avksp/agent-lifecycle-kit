# Аудит реализации

Аудит реализации превращает процедуру `audit-plan-implementation` в
структурированную CLI-команду. Он используется после результата задачи и
независимой проверки, но до принятия задачи контроллером.

## Команды

Проверка отдельной задачи:

```bash
agent-lifecycle audit implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

Итоговая проверка по запуску:

```bash
agent-lifecycle audit final-implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --report work/WS-01/attempt-1/implementation-audit.json \
  --out final/final-implementation-audit.json
```

Команда задачи создаёт `agent-implementation-audit-report.v1`. Итоговая команда
создаёт `agent-final-implementation-audit.v1`.

## Что проверяется

Отчёт задачи объединяет уже существующие контракты жизненного цикла:

- зафиксированный статус плана и его отпечаток;
- ревизия состояния, задача, попытка и исходная ревизия;
- результат задачи и независимая проверка;
- совпадение исполнителя и проверяющего;
- владение путями записи, запрещённые и read-only пути;
- переданные подтверждения относительно обязательных evidence id;
- подтверждение песочницы через `agent-sandbox-receipt.v1`, если изоляция
  обязательна;
- покрытие критериев приёмки по результату и проверке.

Вердикт отчёта: `ACCEPTED`, `REWORK`, `CONTRACT_CHANGE` или `BLOCKED`. Задача
может быть принята workflow gate только когда отчёт имеет `status: PASS` и
`verdict: ACCEPTED`.

## Gates рабочего цикла

План или задача могут потребовать аудит реализации через
`implementationAuditRequired: true` или `implementationAudit: {"required":
true}`. В этом режиме:

- `workflow task-accept` отклоняет задачу без `--implementation-audit`, который
  указывает на принятый отчёт;
- `workflow run` возвращает остановку для задач в проверке или принятых задач,
  если обязательный отчёт отсутствует;
- `workflow finalize` отклоняет запуск, если у принятой обязательной задачи нет
  принятого отчёта аудита реализации.

Запуск также может потребовать итоговый аудит реализации через
`finalImplementationAuditRequired: true` или `implementationAudit.finalRequired:
true`. Тогда прямой `workflow finalize` должен получить
`--final-implementation-audit`.

## Граница

Аудит реализации не исправляет находки и не перефиксирует план. Проблемы
write-set, владения или архитектуры исправляются в рамках зафиксированного
объёма либо возвращаются в планирование. Команды не запускают модели.
