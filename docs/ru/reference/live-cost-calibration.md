# Калибровка реального расхода

Калибровка реального расхода доказывает, что запуск на конкретном хосте и
модели укладывается в заявленные лимиты вызовов, токенов и времени.

Синтетические повторы полезны для локальной регрессии, но не доказывают расход
на реальном Codex, Claude Code, Cursor, Hermes, OpenCode или локальном хосте.

Основные файлы:

- `conformance/core/live-calibration-profile.v1.json` — хосты, сценарии,
  группы проверок, метрики и политика синтетических повторов;
- `conformance/core/budget-targets.v1.json` — целевые p95 и жёсткие лимиты;
- `tools/release/validate_live_calibration.py` — проверка расхода;
- `tools/release/validate_live_host_conformance.py` — проверка операций хоста.

```bash
python tools/release/validate_live_host_conformance.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --baseline conformance/core/adapter-baseline.v1.json \
  --receipt-dir <live-host-receipts-dir> \
  --promoted-hosts codex,claude-code \
  --evidence <live-host-conformance-evidence.json>

python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt-dir <live-calibration-receipts-dir> \
  --promoted-hosts codex,claude-code \
  --evidence <live-calibration-evidence.json>
```

Режимы бюджета:

- `metered` требует утверждённый денежный лимит и учёт стоимости от хоста;
- `subscription` требует лимит числа вызовов и лимит токенов или времени;
- `local` использует такие же ресурсные лимиты, но защищает локальные вычисления.

Если лимит достигнут, обвязка должна остановиться до следующего вызова и
записать блокирующее подтверждение. Критические проверки нельзя тихо
переводить на более слабый маршрут.
