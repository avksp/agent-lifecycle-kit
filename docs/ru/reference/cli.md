# Справочник команд

Основная команда называется `agent-lifecycle`. Она возвращает структурированный
JSON, чтобы результат можно было проверять автоматически.

## Основа

- `agent-lifecycle version`: версия пакета.
- `agent-lifecycle diagnose --no-install-plans`: безопасная проверка
  готовности текущего дерева.
- `agent-lifecycle schema list`: список публичных схем.

## Планирование

- `agent-lifecycle specification`: проверки спецификации.
- `agent-lifecycle plan check`: проверка плана и файла блокировки.
- `agent-lifecycle plan acceptance-check`: проверка трассируемости критериев
  приёмки.
- `issue-to-spec` skill: перевод внешних issue в draft-only ALK specification
  input.
- `agent-lifecycle quality template-list/template-check`: просмотр и проверка
  draft-only task templates.

## Выполнение

- `agent-lifecycle workflow`: переходы жизненного цикла, отчёты задач и
  финальное подтверждение. Для запусков с обязательной проверкой причинной
  цепочки `workflow finalize` принимает
  `--proof-integrity <proof-integrity.json>`.
- `agent-lifecycle runner`: управляемое выполнение с ограничениями ресурсов.
- `agent-lifecycle task compile-small`: small-model packets с output contract и
  compact context receipt.

## Проверка качества

- `agent-lifecycle audit`: проверка плана, реализации и вердиктов.
- `agent-lifecycle quality`: дополнительные проверочные наборы.
- `agent-lifecycle quality bug-recipe-list/bug-recipe-check`: просмотр
  reusable Bug Forensics recipes, которые используют существующие receipts.

## Расход и настройки

- `agent-lifecycle metrics`: отчёты о расходе, экспорт использования и
  рекомендации по режиму.
- `agent-lifecycle metrics usage-export`: экспорт сессий, digest
  подтверждений, токенов, ресурсов, длительности, решений по бюджету и
  необязательного `cost_usd`, если его сообщает metered-хост.
- `agent-lifecycle policy`: adaptive decisions, runtime receipts и
  рекомендательные предложения по настройке правил.

## Адаптеры

- `agent-lifecycle adapter validate`: проверка дескриптора.
- `agent-lifecycle adapter inspect`: безопасный осмотр адаптера.
- `agent-lifecycle adapter install-plan`: пробный план установки без записи.

## Контекст и продолжение

- `agent-lifecycle context`: проверка компактного контекста.
- `agent-lifecycle goal`: снимки цели.
- `agent-lifecycle followup`: учёт продолжений, которые не должны потеряться.
- `agent-lifecycle evidence`: индекс подтверждающих артефактов.
- `agent-lifecycle report status-view/event-feed/progress`: read-only
  представления статуса, событий workflow и lifecycle progress.
