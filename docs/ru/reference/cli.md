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
- `agent-lifecycle plan check`: проверка плана и файла блокировки. Флаг
  `--require-completeness` включает структурную проверку полноты выбранного SDD
  уровня.
- `agent-lifecycle plan completeness-check`: возвращает
  `agent-plan-completeness-validation.v1` с конкретными блокерами по выбранному
  уровню.
- `agent-lifecycle plan acceptance-check`: проверка трассируемости критериев
  приёмки.
- `agent-lifecycle import plan/check`: перевод файла или папки Markdown в
  черновой план-кандидат. Флаг `--dialect openspec|spec-kit|bmad|spec-kitty`
  выбирает профиль OpenSpec, Spec Kit, BMAD или Spec Kitty; результат требует
  проверки и заморозки перед реализацией.
- навык `issue-to-spec`: перевод внешних тикетов в черновой вход спецификации
  ALK.
- `agent-lifecycle quality template-list/template-check`: просмотр и проверка
  черновых шаблонов задач.
- Частые сценарии собраны в `docs/ru/lifecycle-cookbook.md`: исследование,
  проверка Markdown, проверка изменений и аудит реализации.

## Выполнение

- `agent-lifecycle workflow run`: проверяет связь зафиксированного плана и
  сохранённого состояния, затем возвращает следующий шаг для хоста без записи
  в состояние и без запуска модели. Добавьте `--progress-hook stderr`, чтобы
  показать прогресс в stderr, или `--progress-hook receipt --progress-receipt
  <path>`, чтобы сохранить `agent-progress-hook-receipt.v1` без изменения JSON
  в stdout.
- `agent-lifecycle workflow`: переходы жизненного цикла, отчёты задач и
  финальное подтверждение. Для запусков с обязательной проверкой причинной
  цепочки `workflow finalize` принимает
  `--proof-integrity <proof-integrity.json>`; для обязательного решения
  завершения принимает `--completion-gate-receipt <completion-gate.json>`.
  Если план требует аудит реализации, `workflow task-accept` принимает
  `--implementation-audit <implementation-audit.json>`, а `workflow finalize`
  принимает `--final-implementation-audit <final-implementation-audit.json>`.
  Для плана с обязательной групповой проверкой на финальном аудите
  `workflow finalize` принимает `--review-mesh-quorum <path>`.
- Управляемый вывод прогресса поддерживают только `workflow run`,
  `workflow task-result`, `workflow task-accept` и `workflow finalize`.
  `ALK_PROGRESS_HOOK=stderr` можно использовать в обёртках; установка плагина
  сама по себе не доказывает полный жизненный цикл.
- `agent-lifecycle runner`: управляемое выполнение с ограничениями ресурсов.
- `agent-lifecycle task compile-small`: пакеты для маленьких моделей с
  контрактом результата и компактным артефактом контекста.

## Проверка качества

- `agent-lifecycle audit`: проверка плана, реализации и вердиктов.
- `agent-lifecycle audit implementation`: структурированный отчёт
  `agent-implementation-audit-report.v1` по результату задачи и независимой
  проверке. Если зафиксированный план требует групповую проверку для аудита
  реализации, используйте `--review-mesh-quorum <path>`.
- `agent-lifecycle audit final-implementation`: итоговый отчёт
  `agent-final-implementation-audit.v1` перед финальным подтверждением
  рабочего цикла.
- `agent-lifecycle quality`: дополнительные проверочные наборы.
- `agent-lifecycle quality bug-recipe-list/bug-recipe-check`: просмотр
  переиспользуемых рецептов профиля расследования ошибок, которые используют
  существующие артефакты.

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
- `agent-lifecycle review-mesh profile`: создаёт профиль групповой проверки с
  лимитами по токенам/ресурсам и нейтральными классами моделей.
- `agent-lifecycle review-mesh recommend`: анализирует текст задачи, файл
  задачи, артефакт приёма задачи или манифест плана и возвращает
  `agent-review-mesh-recommendation.v1`. Полученный артефакт только рекомендует
  режим: он не создаёт назначения, не запускает адаптеры и не включает
  обязательные контрольные точки.
- `agent-lifecycle review-mesh assign/import-result/synthesize/quorum`:
  создаёт пакеты назначений для выполнения на стороне хоста, импортирует
  обезличенный результат проверяющего, объединяет выводы и формирует артефакт
  кворума. Эти команды не вызывают модели и не запускают CLI хоста.

## Адаптеры

- `agent-lifecycle adapter validate`: проверка дескриптора.
- `agent-lifecycle adapter inspect`: безопасный осмотр адаптера.
- `agent-lifecycle adapter install-plan`: пробный план установки без записи.
- `agent-lifecycle adapter session start/status/resume/promote`: запись и
  возобновление сессий адаптеров. Обычная интерактивная сессия возвращает
  `WAITING_FOR_TASK`; повышенная сессия связывается с состоянием рабочего цикла
  и задачей.
- `agent-lifecycle adapter task start --adapter <id> (--file task.md |
  --text "...")`: принимает задачу для выбранного адаптера. Обычный текст и
  Markdown возвращают `agent-adapter-task-start-receipt.v1` со статусом
  `REVIEW_REQUIRED`; `--task-file` и `--task-text` являются псевдонимами. В
  подтверждении может быть рекомендательное поле `reviewMeshRecommendation`,
  если дополнительные проверяющие могут помочь, но вход остаётся черновым.
  Структурированный `agent-adapter-task-run-request.v1` или зафиксированный
  манифест с `--state`, `--lock`, `--task`, `--operation-id`,
  `--expected-revision` и `--source-revision` передаются в управляемый запуск.
- `agent-lifecycle adapter run`: связывает сессию адаптера с зафиксированным
  состоянием рабочего цикла и возвращает управляемый следующий шаг ALK. Для
  этого управляемого пути прогресс по умолчанию показывается в stderr, а JSON stdout
  остаётся `agent-adapter-session-receipt.v1`.

## Контекст и продолжение

- `agent-lifecycle context`: проверка компактного контекста.
- `agent-lifecycle goal`: снимки цели.
- `agent-lifecycle followup`: учёт продолжений, которые не должны потеряться.
- `agent-lifecycle evidence`: индекс подтверждающих артефактов.
- `agent-lifecycle report status-view/event-feed/progress/change-summary`:
  представления без записи для статуса, событий рабочего цикла, прогресса
  жизненного цикла и счётчика изменений. Прогресс поддерживает ограниченный
  режим `--watch` и явный текстовый вывод `--terminal`.
- `agent-lifecycle report progress-bridge`: создаёт
  `agent-progress-bridge-receipt.v1` для обёрток адаптеров, которым нужен
  стабильное JSON-подтверждение и, при необходимости, текст для терминала.
