# Аудит реализации

Аудит реализации превращает процедуру `audit-plan-implementation` в
структурированную CLI-команду. Он используется после результата задачи и
независимой проверки, но до принятия задачи контроллером.

## Команды

Проверка отдельной задачи:

```bash
agent-lifecycle audit implementation \
  --manifest work/plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

Итоговая проверка по запуску:

```bash
agent-lifecycle audit final-implementation \
  --manifest work/plans/package/plan.manifest.json \
  --state run.state.json \
  --report work/WS-01/attempt-1/implementation-audit.json \
  --out final/final-implementation-audit.json
```

Команда задачи создаёт `agent-implementation-audit-report.v1`. Итоговая команда
создаёт `agent-final-implementation-audit.v1`.

## Дельта-аудит повторной попытки

После архивирования попытки и создания нового результата сформируйте
ограниченное подтверждение для следующего независимого проверяющего:

```bash
agent-lifecycle audit delta \
  --manifest tasks/package/plan.manifest.json \
  --lock tasks/package/plan.lock.json \
  --state work/package/run.state.json \
  --task WS-01 \
  --dependency-report work/evidence/module-dependencies.json \
  --validation-selection work/evidence/validation-selection.json \
  --finding-check-binding work/findings/F-1-binding.json \
  --finding-check-evidence work/findings/F-1-evidence.json \
  --out work/WS-01/attempt-2/delta-audit.json
```

Read-only команда создаёт `agent-rework-delta-audit-receipt.v1`. Она получает
соседние попытки из состояния workflow, проверяет зафиксированную область
находки и использует общий граф зависимостей для определения влияния. Команда
не запускает проверку, модель или процесс хоста. Отсутствующая или устаревшая
линия происхождения, неполная область, защищённые пути, неопределённость графа,
изменение полномочий или ошибка replay возвращают `FULL_AUDIT_REQUIRED`.
Дельта-подтверждение не заменяет независимую приёмку задачи и свежий полный
финальный аудит.

## Проверка папки плана и реализации

Когда один человек передаёт другому план и готовую реализацию, их можно
проверить одной командой:

```bash
agent-lifecycle audit package \
  --plan-dir tasks/release-1-63 \
  --state work/release-1-63/run.state.json \
  --base main \
  --require-frozen \
  --require-implementation \
  --strict \
  --out work/release-1-63/evidence/package-audit.json
```

`--plan-dir` находит канонические файлы плана. При указании `--state` команда
находит отчёты аудита реализации под папкой артефактов состояния. Чтобы явно
задать список отчётов, передайте несколько параметров `--report <путь>`. Для
проверки только плана используйте команду без `--state`.

Команда создаёт `agent-plan-package-audit-report.v1`. Статус `PASS` означает,
что все запрошенные проверки плана и реализации пройдены. `REVIEW_REQUIRED`
означает, что пакет можно проверить, но один из этапов ещё не завершён,
например план остаётся черновым или отсутствует состояние запуска. `FAIL`
содержит конкретные причины блокировки. Параметр `--strict` превращает любой
результат кроме `PASS` в ошибку для передачи пакета или проверки в CI после
записи отчёта.

## Что проверяется

Отчёт задачи объединяет уже существующие контракты жизненного цикла:

- зафиксированный статус плана и его отпечаток;
- ревизия состояния, задача, попытка и исходная ревизия;
- результат задачи и независимая проверка;
- текущий набор файлов задачи и отпечатки их содержимого по Git, повторно
  вычисленные от зафиксированной исходной ревизии; значения `--path`, переданные
  вызывающей стороной, не могут заменить эти данные;
- совпадение исполнителя и проверяющего;
- владение путями записи, запрещённые и read-only пути;
- переданные подтверждения относительно обязательных evidence id;
- подтверждение песочницы через `agent-sandbox-receipt.v1`, если изоляция
  обязательна;
- покрытие критериев приёмки по результату и проверке.

Вердикт отчёта: `ACCEPTED`, `REWORK`, `CONTRACT_CHANGE` или `BLOCKED`. Задача
может быть принята workflow gate только когда отчёт имеет `status: PASS` и
`verdict: ACCEPTED`.

Если отчёт возвращает `REWORK` по открытым находкам внутри зафиксированных
границ, передайте его в `workflow task-rework --implementation-audit <path>`
вместе с выбранными идентификаторами находок. ALK проверит связь и независимость
отчёта, сохранит его идентификатор в истории попытки и потребует новый
актуальный результат и аудит для следующей попытки.

Для локальных исходов задачи в v4 канонической мутацией является `workflow
task-review-apply`. Она принимает текущий результат задачи, независимую
проверку и, когда требуется, аудит реализации, затем применяет `ACCEPTED`,
`REWORK`, `CONTRACT_CHANGE` или `BLOCKED`, не меняя состояние соседних задач.

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
