# Лестница проверок

Лестница проверок выбирает минимальный разрешённый набор быстрой обратной
связи для изменённых файлов, сохраняя полный релизный гейт. Выбор
детерминирован, работает только для чтения и не содержит команд: ALK возвращает
ID проверок, но не выполняет строки команд.

## Зафиксированные входы

План с включённой лестницей объявляет оба необязательных поля в `validation`:

- `checkCatalog`: закрытый объект `agent-validation-check-catalog.v1`, где
  стабильный ID связан с digest одной точной строки `validation.commands`;
- `validationLadderProfile`: путь и digest закрытого
  `agent-validation-ladder-profile.v1`, который связывает буквальные префиксы
  репозитория с ID уровней `TASK_FAST`, `TASK_ACCEPTANCE` или `RELEASE_FULL`.

Поля задаются только вместе и входят в plan lock. Профиль не содержит команд.
Glob-пути, неизвестные ID, противоречивые дубликаты, нечитаемые или устаревшие
байты профиля и несовпадающий lineage plan/lock блокируют выбор.

## Выбор проверок

```bash
agent-lifecycle workflow validation-select \
  --state <run.state.json> \
  --task <task-id> \
  --manifest <plan.manifest.json> \
  --lock <plan.lock.json> \
  --snapshot <task-change-set.json> \
  --out <validation-selection.json>
```

Результат `agent-validation-selection.v1` содержит уровень и ID проверок, а
также `commandsExecuted: false` и `stateWritten: false`. Хост или оператор
сопоставляет ID с зафиксированным каталогом, выполняет точные команды и
сохраняет обычное evidence. Сам selector не принимает задачу.

## Консервативный минимум

План без необязательного профиля выбирает `RELEASE_FULL`. Валидный профиль без
совпадения также выбирает `RELEASE_FULL`. Изменения защищённых путей релиза,
безопасности, архитектуры, политик, контрактов, документации и публикации
всегда требуют `RELEASE_FULL`; дополнения профиля могут только расширять этот
набор.

Для плана с включённой лестницей финализация требует свежий
`agent-release-full-validation-receipt.v1`, переданный через `workflow finalize
--release-full-receipt`. Набор пройденных ID должен точно совпадать с полным
обязательным набором, а lineage plan, lock, source, текущего дерева и каталога
должен совпадать. Фокусные receipts его не заменяют, а существующие post-merge
publication gates остаются отдельными.
