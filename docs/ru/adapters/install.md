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

## Kimi Code

```bash
kimi --version
agent-lifecycle adapter install-plan --descriptor adapters/kimi-code/adapter.descriptor.json
```

## Граница продвижения

Пробная установка, осмотр и синтетический прогон не повышают зрелость адаптера.
Для `VERIFIED` нужны подтверждения из реального запуска на конкретном хосте,
учёт расхода, принятые обезличенные доказательства и финальное подтверждение
жизненного цикла.
