# Task Templates

Task templates — draft-only заготовки для подготовки ALK plan. Они помогают
структурировать входную задачу, но не утверждают план, не запускают выполнение и
не заменяют review/freeze gates.

Доступные шаблоны:

- `bugfix`: defect repair с optional Bug Forensics profile.
- `idea-to-pr`: путь от идеи до reviewed implementation plan.
- `pr-review`: проверка существующего изменения.
- `merge-conflict-repair`: минимальный repair merge conflicts.
- `release-readiness`: подготовка release candidate и evidence.

Проверка:

```bash
agent-lifecycle quality template-list
agent-lifecycle quality template-check --template-id bugfix
```

Все templates должны содержать `DRAFT-ONLY`, требовать review/freeze и не
хранить runtime defaults.
