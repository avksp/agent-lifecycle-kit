# Подтверждение промышленной готовности

Промышленная готовность находится вне обычной офлайн-проверки исходного релиза.

Для такого заявления нужны внешние подтверждения:

- подписанная матрица CI для Ubuntu, macOS и Windows на CPython 3.11, 3.12 и
  3.13;
- подписанное подтверждение нейтральности релиза;
- подтверждение соответствия жизненного цикла для каждого продвигаемого хоста;
- калибровка реального расхода;
- независимый финальный аудит, подтверждающий, что релиз не заявляет поддержку
  шире имеющихся доказательств.

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

Имена конкретных моделей, ключи провайдера, подписки и локальные настройки не
являются переносимыми данными ядра. Они остаются в локальных профилях хоста или
в обезличенных подтверждениях.

Режим `metered` доказывает учёт стоимости в рамках утверждённого лимита.
`subscription` и `local` доказывают ограниченный расход через лимиты вызовов,
токенов и времени. Ни один режим не отменяет требования к live conformance,
калибровке, нейтральности, CI и независимому финальному аудиту.
