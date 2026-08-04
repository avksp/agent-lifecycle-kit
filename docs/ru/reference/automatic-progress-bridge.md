# Отображение прогресса для адаптеров

Progress bridge помогает адаптеру показать прогресс ALK в терминале, пока
запуск модели остаётся под управлением хоста. Это слой отображения поверх уже
существующего состояния рабочего цикла, артефактов использования и счётчика
изменений.

Он устроен минимально:

- `agent-lifecycle report progress --terminal` печатает текущие строки
  прогресса как текст вместо JSON.
- `agent-lifecycle report progress-bridge` возвращает
  `agent-progress-bridge-receipt.v1` для обёрток адаптеров.
- `agent-progress-bridge-config.v1` фиксирует уровень поддержки адаптера.
- Существующие JSON-команды остаются стандартным машинным контрактом.

Bridge не является источником правды. Авторитетным остаётся состояние рабочего
цикла. Receipt указывает `readOnly: true`, `modelCallsStarted: false`,
`stateWritten: false`, `tokenSpendForProgress: false` и
`hostTelemetryParsedInCore: false`.

## Уровни поддержки

| Уровень | Значение |
| --- | --- |
| `AUTO` | Интеграция хоста может вызывать bridge из своего lifecycle hook. |
| `WATCH` | Оператор или обёртка может запустить наблюдение в отдельном терминале. |
| `MANUAL` | Оператор может выполнить разовую команду прогресса. |
| `UNSUPPORTED` | Поддерживаемого hook или описанной обёртки пока нет. |

Уровень поддержки прогресса не меняет зрелость адаптера. `VERIFIED` адаптер
может иметь ручной прогресс, а `EXPERIMENTAL` адаптер может описывать
безопасную ручную команду.

## Команды

JSON остаётся режимом по умолчанию:

```bash
agent-lifecycle report progress --state <workflow-state.json>
```

Текстовый вывод включается явно:

```bash
agent-lifecycle report progress --state <workflow-state.json> --terminal
```

Обёртки адаптеров используют bridge receipt, когда нужен стабильный JSON и
готовый текст для терминала:

```bash
agent-lifecycle report progress-bridge \
  --adapter codex \
  --support-level WATCH \
  --hook-point side-terminal-watch \
  --state <workflow-state.json> \
  --usage-receipt <usage.json> \
  --change-summary <changes.json>
```

Добавьте `--terminal`, чтобы вывести только текст. Добавьте `--out
<receipt.json>`, чтобы сохранить JSON receipt и одновременно вывести текст.

## Токены и изменения

Токены берутся только из подтверждённых хостом usage receipts. Если данных нет
или они не подтверждены, выводится `↑?/↓? tok`; ALK не вычисляет токены
самостоятельно. Изменения в коде берутся из `agent-change-summary-receipt.v1`,
который создаёт отдельная команда для Git diff.

## Ответственность хоста

Адаптеры хостов отвечают за нативный запуск, отмену, ожидание, provider/model
telemetry и автоматические hook. Core ALK не патчит host CLI, не запускает
фоновых демонов, не добавляет prompt injection и не разбирает host-specific
telemetry.
