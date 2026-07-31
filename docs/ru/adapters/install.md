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
связке ZAI GLM 5.2. Live promotion использовал ограниченные no-session/no-profile
запуски с явным provider/model и проверкой чистого worktree после каждого
вызова.

## Kimi Code

```bash
kimi --version
agent-lifecycle adapter install-plan --descriptor adapters/kimi-code/adapter.descriptor.json
```

## Grok Build

```bash
grok build --help
agent-lifecycle adapter install-plan --descriptor adapters/grok-build/adapter.descriptor.json
```

Grok Build остаётся `EXPERIMENTAL`: ACP-путь должен пройти локальный probe, а
неудачный probe фиксируется как fail-closed evidence.

## OpenInterpreter

```bash
interpreter --version
agent-lifecycle adapter install-plan --descriptor adapters/openinterpreter/adapter.descriptor.json
```

OpenInterpreter описан как host-local compatible CLI projection без заявления
о live promotion.

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
