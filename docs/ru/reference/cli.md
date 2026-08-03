# Справочник команд

Основная команда называется `agent-lifecycle`. Она возвращает структурированный
JSON, чтобы результат можно было проверять автоматически.

## Основа

- `agent-lifecycle version`: версия пакета.
- `agent-lifecycle diagnose --no-install-plans`: безопасная проверка
  готовности текущего дерева.
- `agent-lifecycle schema list`: список публичных схем.

## Планирование

- `agent-lifecycle specification`: проверки спецификации и проверки
  завершения.
- `agent-lifecycle plan check`: проверка плана и файла блокировки.
- `agent-lifecycle plan acceptance-check`: проверка трассируемости критериев
  приёмки.
- `issue-to-spec` skill: перевод внешних issue в черновой вход спецификации
  ALK.
- `agent-lifecycle quality template-list/template-check`: просмотр и проверка
  черновых шаблонов задач.

## Выполнение

- `agent-lifecycle workflow run`: проверяет связь зафиксированного плана и
  сохранённого состояния, затем возвращает следующий шаг для хоста без записи
  в состояние и без запуска модели.
- `agent-lifecycle workflow`: переходы жизненного цикла, отчёты задач и
  финальное подтверждение. Для запусков с обязательной проверкой причинной
  цепочки `workflow finalize` принимает
  `--proof-integrity <proof-integrity.json>`; для обязательного решения
  завершения принимает `--completion-gate-receipt <completion-gate.json>`.
  Если план требует аудит реализации, `workflow task-accept` принимает
  `--implementation-audit <implementation-audit.json>`, а `workflow finalize`
  принимает `--final-implementation-audit <final-implementation-audit.json>`.
- `agent-lifecycle runner`: управляемое выполнение с ограничениями ресурсов.
- `agent-lifecycle task compile-small`: пакеты для маленьких моделей с
  контрактом результата и компактным артефактом контекста.

## Проверка качества

- `agent-lifecycle audit`: проверка плана, реализации и вердиктов.
- `agent-lifecycle audit implementation`: структурированный отчёт
  `agent-implementation-audit-report.v1` по результату задачи и независимой
  проверке.
- `agent-lifecycle audit final-implementation`: итоговый отчёт
  `agent-final-implementation-audit.v1` перед финальным подтверждением
  workflow.
- `agent-lifecycle quality`: дополнительные проверочные наборы.
- `agent-lifecycle quality bug-recipe-list/bug-recipe-check`: просмотр
  переиспользуемых рецептов Bug Forensics, которые используют существующие
  артефакты.

## Расход и настройки

- `agent-lifecycle metrics`: отчёты о расходе, экспорт использования и
  рекомендации по режиму.
- `agent-lifecycle metrics outcome-index/quality-signals/learn-recommend`:
  рекомендательное обучение по локальным артефактам без автоматического
  применения.
- `agent-lifecycle metrics usage-export`: экспорт сессий, отпечатков
  подтверждений, токенов, ресурсов, длительности, решений по бюджету и
  необязательного `cost_usd`, если его сообщает тарифицируемый хост.
- `agent-lifecycle policy`: адаптивные решения, артефакты правил запуска и
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
- `agent-lifecycle report status-view/event-feed/progress`: представления без
  записи для статуса, событий рабочего цикла и прогресса жизненного цикла.
