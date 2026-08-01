# Small-model packets

Small-model packets уменьшают execution surface для маленьких или локальных
моделей без ослабления lifecycle. Они компилируются из frozen
`agent-task-packet.v1` и сохраняют plan digest, acceptance ids, evidence ids и
write-scope authority.

```bash
agent-lifecycle task compile-small \
  --manifest <plan.manifest.json> \
  --context-profile profiles/small-context-profile.v1.json \
  --target-window 4k-strict \
  --write
```

CLI возвращает `agent-small-model-packet-compile-result.v1`. Пакеты имеют
schema `agent-small-model-task-packet.v1`, индекс —
`agent-small-model-task-packet-index.v1`.

Каждый packet содержит exact write scope, compact context receipt и
`agent-small-model-output-contract.v1`. Worker должен вернуть
`agent-small-model-task-result.v1`; `agent-small-model-output-validation.v1`
падает, если поля отсутствуют, digest не совпадает или changed files выходят
за write scope.

Если передан adaptive lifecycle decision, small-model packet selection
разрешается только при допустимом quality floor. Strict/release floors
блокируют automatic small-model packet selection. Такие packets не заменяют
critical review, final audit или production promotion evidence.
