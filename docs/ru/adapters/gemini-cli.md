# Адаптер Gemini CLI

Проекция Gemini CLI является `EXPERIMENTAL`. Она содержит локальный
контролируемый запуск, обвязку реального хоста и манифест возможностей, но не
заявляет `VERIFIED`, промышленную готовность или конкретные имена моделей в
переносимых артефактах.

Локальная проверка перед реальным запуском:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/gemini-cli/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/gemini-cli/adapter.descriptor.json \
  --skip-host-commands

python tools/release/validate_adapter_conformance.py \
  --baseline conformance/core/adapter-baseline.v1.json \
  --host gemini-cli \
  --evidence <adapter-conformance-evidence.json>
```

Gemini CLI `0.46.0` прошёл безопасный локальный осмотр команд версии, справки,
режима без интерфейса, потокового JSON, выбора модели, прав доступа, навыков,
расширений, MCP и локального маршрута Gemma. Резюме:
`docs/adapters/evidence/gemini-cli-0.10.0.md`.

Текущая причина блокировки: `BLOCKED_UNSUPPORTED_CLIENT_TIER`. Локальный
уровень Gemini Code Assist не даёт получить подтверждение реального запуска,
поэтому зрелость остаётся `EXPERIMENTAL`.

Локальный нормализатор `stream-json` имеет состояние `FIXTURE_ONLY`.
Исполнитель и испытательный стенд используют один ограниченный разбор, но его
результат остаётся `ESTIMATED` и не подходит для S1/S2 до отдельного
подтверждения диапазона версий Gemini CLI. Подробнее:
[локальный учёт токенов хоста](../reference/host-local-token-accounting.md).

## Запуск только для планирования

Точная версия профиля: `0.46.0`. Состояние профиля: `CANDIDATE`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Режим согласования плана и передача через стандартный ввод образуют статический профиль-кандидат, но принятого подтверждения реального запуска пока нет.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter gemini-cli --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/gemini-cli.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/gemini-cli.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/gemini-cli.json
```

Успешная проверка версии не разрешает запуск планирования.
`managedLaunch.status` остаётся `WRAPPER_ONLY`, а зрелость адаптера не повышает
состояние поддержки планирования. Подробнее: [запуск адаптера только для
планирования](../reference/planning-only-launch.md).
