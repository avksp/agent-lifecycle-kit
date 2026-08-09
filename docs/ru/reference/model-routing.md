# Маршрутизация моделей

Маршрутизация моделей выбирает нейтральный класс модели для этапа жизненного
цикла или попытки задачи. Она не вызывает API провайдера и не записывает
конкретные имена моделей в переносимые планы, пакеты задач, lock-файлы или
состояние workflow.

```bash
agent-lifecycle model profile-check \
  --profile profiles/model-routing-profile.v1.json

agent-lifecycle model profile-check \
  --type host \
  --profile <host-model-profile.json>

agent-lifecycle model route \
  --profile profiles/model-routing-profile.v1.json \
  --host-profile <host-model-profile.json> \
  --request <model-route-request.json>

agent-lifecycle model usage-check \
  --receipt <model-usage-receipt.json> \
  --route-decision <model-route-decision.json> \
  --budget-targets conformance/core/budget-targets.v1.json
```

`model route` детерминирован: одинаковый запрос и одинаковые профили дают один
и тот же отпечаток решения. Сигналы ошибок могут повышать класс модели, но не
понижают его ниже уже выбранного безопасного уровня.

Классы моделей остаются нейтральными: `no-model`, `budget`, `local-compact`,
`standard-code`, `local-standard-code`, `strong-reasoning`,
`local-strong-review` и `specialist-review`. Конкретные имена моделей хранятся
только в локальных профилях хоста и могут быть замаскированы или не
коммититься.

Для операций с моделью нужен `agent-lifecycle-model-usage-receipt.v1`, привязанный
к тому же запуску, задаче, попытке, отпечатку плана, исходной ревизии и
решению маршрутизации.

Обычное подтверждение содержит `inputTokens`, `outputTokens`,
`billableTokens`, `cumulativeContextBytes`, `toolCalls` и `wallSeconds`.
Для попытки с учётом риска добавляется `usage.invocations`. Профиль проверяет
`billableTokens`, `invocations` и `wallSeconds`; превышение любого ограничения
отклоняет `workflow task-result`.

Дополнительное поле обязательно только после разрешения попытки командой
`workflow task-start --risk-profile <path>`. Полный сценарий приведён в разделе
[Запуск с учётом риска](risk-aware-execution.md).

Локальный нормализатор адаптера может сформировать то же подтверждение как
сопутствующий результат, не меняя схему операции хоста. Ядро принимает его как
подтверждённый расход только при одновременном наличии `source: host`,
`status: ATTESTED` и принятого состояния нормализатора. Подробнее:
[локальный учёт токенов хоста](host-local-token-accounting.md).
