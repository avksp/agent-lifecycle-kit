# Установка адаптеров

Эта страница описывает безопасный порядок установки адаптеров. Команды ниже не
заявляют `VERIFIED`: зрелость адаптера повышается только после проверки на
реальном хосте, калибровки расхода и финального подтверждения жизненного цикла.

## Общие проверки

```bash
agent-lifecycle adapter validate --descriptor adapters/codex/adapter.descriptor.json
agent-lifecycle adapter inspect --descriptor adapters/codex/adapter.descriptor.json
agent-lifecycle adapter install-plan --descriptor adapters/codex/adapter.descriptor.json
```

## Host-local секреты

Адаптеры, которые вызывают реальную модель, должны получать ключи через
штатный механизм хоста: переменные окружения, credential store хоста или
операторский secret launcher. ALK не хранит provider keys в tracked config,
descriptor, receipts или release evidence.

Для live harness можно использовать `--host-env-file`, если ключ не нужно
экспортировать глобально. Это приватный dotenv-style файл оператора вне
репозитория; каждое имя переменной явно разрешается для конкретного запуска:

```bash
python tools/live_hosts/<host>_harness.py \
  --mode preflight \
  --host-env-file ~/.config/alk/hosts/<host>.env \
  --host-env-allow PROVIDER_API_KEY \
  --report work/<release>/evidence/<host>-preflight.json
```

Harness передаёт дочернему host-процессу только разрешённые имена и пишет в
evidence только `agent-host-env-file-redacted.v1`. Проверку отсутствия значений
секретов в отчётах выполняет `tools/release/validate_host_env_hygiene.py`.

Это правило относится ко всем provider-flexible адаптерам. Если хост умеет
переключать providers или models, выбранный provider остаётся источником имени
и механизма credential; ALK получает только явно разрешённое оператором имя
переменной для текущего harness-запуска.

## Codex

```bash
codex plugin list
agent-lifecycle adapter install-plan --descriptor adapters/codex/adapter.descriptor.json
```

## Claude Code

```bash
claude plugin list
agent-lifecycle adapter install-plan --descriptor adapters/claude/adapter.descriptor.json
```

## Cursor

```bash
cursor --version
agent-lifecycle adapter install-plan --descriptor adapters/cursor/adapter.descriptor.json
```

## OpenCode

```bash
opencode --version
agent-lifecycle adapter install-plan --descriptor adapters/opencode/adapter.descriptor.json
```

## Hermes

```bash
hermes --version
agent-lifecycle adapter install-plan --descriptor adapters/hermes/adapter.descriptor.json
```

## Qwen Code

```bash
qwen --version
agent-lifecycle adapter install-plan --descriptor adapters/qwen-code/adapter.descriptor.json
```

## Gemini CLI

```bash
gemini --version
agent-lifecycle adapter install-plan --descriptor adapters/gemini-cli/adapter.descriptor.json
```

## Goose

```bash
goose --help
agent-lifecycle adapter install-plan --descriptor adapters/goose/adapter.descriptor.json
```

Goose имеет host-specific `VERIFIED` только для Goose `1.45.0` на проверенной
host-local provider/model связке. Live promotion использовал ограниченные
no-session/no-profile запуски с явным provider/model и проверкой чистого
worktree после каждого вызова.

## Kimi Code

```bash
kimi --version
agent-lifecycle adapter install-plan --descriptor adapters/kimi-code/adapter.descriptor.json
```

## Grok Build

```bash
grok --version
grok agent --help
agent-lifecycle adapter install-plan --descriptor adapters/grok-build/adapter.descriptor.json
```

Grok Build имеет host-specific `VERIFIED` для Grok Build `0.2.117` на
проверенной host-local provider/model связке. ACP-путь остаётся probe-gated, а
неудачный probe фиксируется как fail-closed evidence.

## OpenInterpreter

```bash
interpreter --version
interpreter doctor --json
agent-lifecycle adapter install-plan --descriptor adapters/openinterpreter/adapter.descriptor.json
```

OpenInterpreter имеет host-specific `VERIFIED` для `interpreter` 0.0.34 на
проверенной host-local provider/model связке. Учётные данные выбранной модели
должны быть видны процессу `interpreter` перед локальным live rerun.
OpenInterpreter берёт имя нужной переменной из выбранного provider: custom
provider указывает `env_key` в `~/.openinterpreter/config.toml` или
`.openinterpreter/config.toml`, а встроенные providers используют свои
документированные переменные. Значение ключа должно приходить из окружения или
credential store хоста, а не из repository config.

Чтобы дать ключ выбранного provider только ALK harness-процессу, помести его в
приватный operator env-file и явно разреши это имя:

```bash
python tools/live_hosts/openinterpreter_harness.py \
  --mode preflight \
  --interpreter-model <model-id> \
  --host-env-file ~/.config/alk/hosts/openinterpreter.env \
  --host-env-allow PROVIDER_API_KEY \
  --budget-mode subscription \
  --max-invocations 14 \
  --max-billable-tokens 1000 \
  --allow-live \
  --report work/release-1-18/evidence/preflight/openinterpreter-preflight-report.json
```

`PROVIDER_API_KEY` нужно заменить на имя env-key из выбранного provider.

## Pi

```bash
agent-lifecycle adapter install-plan --descriptor adapters/pi/adapter.descriptor.json
```

Pi описан как RPC/JSON и AGENTS/agentskills projection. Offline fixtures не
повышают зрелость адаптера.

## Граница продвижения

Пробная установка, осмотр и синтетический прогон не повышают зрелость адаптера.
Для `VERIFIED` нужны подтверждения из реального запуска на конкретном хосте,
учёт расхода, принятые обезличенные доказательства и финальное подтверждение
жизненного цикла.
