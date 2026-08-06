# Непрерывность плана

Непрерывность плана нужна для работы с несколькими репозиториями или для
компактной передачи зафиксированного плана на независимую проверку. Обычный
путь для одного репозитория остаётся основным.

Ссылки на репозитории должны быть явными:

- `id`, `repoId`, `owner`, `access`;
- `access` равен `read-only` или `write-scoped`;
- для `write-scoped` обязательно перечисляются разрешённые пути;
- абсолютные локальные пути и выход за границы запрещены.

```bash
agent-lifecycle plan refs-check --manifest <plan.manifest.json>
agent-lifecycle plan snapshot --manifest <plan.manifest.json> --out <plan-snapshot.json>
agent-lifecycle plan reconcile --manifest <plan.manifest.json> --snapshot <plan-snapshot.json>
agent-lifecycle plan handoff --manifest <plan.manifest.json> --snapshot <plan-snapshot.json> --out <handoff.json>
```

Снимок связывает manifest, базовую ревизию, спецификацию, критерии приёмки и
ссылки на репозитории. Перед продолжением работы `plan reconcile` сравнивает
снимок с текущим manifest и отказывает при расхождении.

Handoff-пакет даёт проверяющему краткую личность плана, базовую ревизию,
сводку репозиториев, владельцев работ и критерии приёмки. Полные артефакты
остаются источником правды.
