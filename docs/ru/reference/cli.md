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

## Выполнение

- `agent-lifecycle workflow`: переходы жизненного цикла, отчёты задач и
  финальное подтверждение.
- `agent-lifecycle runner`: управляемое выполнение с ограничениями ресурсов.

## Проверка качества

- `agent-lifecycle audit`: проверка плана, реализации и вердиктов.
- `agent-lifecycle quality`: дополнительные проверочные наборы.

## Расход и настройки

- `agent-lifecycle metrics`: отчёты о расходе и рекомендации по режиму.
- `agent-lifecycle policy`: рекомендательные предложения по настройке правил.

## Адаптеры

- `agent-lifecycle adapter validate`: проверка дескриптора.
- `agent-lifecycle adapter inspect`: безопасный осмотр адаптера.
- `agent-lifecycle adapter install-plan`: пробный план установки без записи.

## Контекст и продолжение

- `agent-lifecycle context`: проверка компактного контекста.
- `agent-lifecycle goal`: снимки цели.
- `agent-lifecycle followup`: учёт продолжений, которые не должны потеряться.
- `agent-lifecycle evidence`: индекс подтверждающих артефактов.
