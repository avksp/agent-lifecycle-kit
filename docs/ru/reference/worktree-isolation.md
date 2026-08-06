# Изоляция рабочего дерева

Артефакты изоляции рабочего дерева показывают, что попытка задачи выполнялась в
ограниченной рабочей области и не перезаписала чужие локальные изменения. Ядро
ALK записывает и проверяет подтверждения, но не создаёт, не удаляет и не
переписывает рабочие деревья.

`agent-worktree-isolation-policy.v1` задаёт:

- относительный корень рабочей области;
- разрешённые корни записи;
- сохранять ли неудачные попытки по умолчанию;
- требует ли очистка явного разрешения оператора.

```bash
agent-lifecycle worktree policy-check --policy <worktree-policy.json>

agent-lifecycle worktree receipt \
  --state <run.state.json> \
  --policy <worktree-policy.json> \
  --task <task-id> \
  --attempt <n> \
  --worktree-path <relative-path> \
  --baseline-ref <ref> \
  --baseline-sha <sha> \
  --changed-file <path> \
  --reason "<reason>" \
  --out <worktree-receipt.json>

agent-lifecycle worktree check \
  --receipt <worktree-receipt.json> \
  --state <run.state.json> \
  --policy <worktree-policy.json>
```

`agent-worktree-writeback-receipt.v1` фиксирует решение применить или отбросить
изменения из изолированной области. Runtime-ограничения при этом остаются
отдельной схемой `agent-sandbox-receipt.v1`.
