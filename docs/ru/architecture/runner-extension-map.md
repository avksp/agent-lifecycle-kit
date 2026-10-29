# Карта расширений runner

Runner ограничен записью состояния переходов и счётчиков ресурсов. Фактические lifecycle mutations он делегирует существующим workflow commands и adapter-session bridges.

## Сохранение worktree

Текущая интеграция:

- переходы попыток могут проверять isolation receipt через `validate_attempt_isolation_receipt`;
- история переходов хранит evidence ids и isolation receipt digests, а не platform paths как authority;
- attempt snapshots и sandbox receipts находятся рядом с runner; cleanup остаётся консервативным и требует operator approval.

Runner не должен напрямую удалять worktrees или переписывать файлы пользователя.

## Приём событий host

Текущая граница интеграции:

- adapter events можно прикреплять к transition evidence по evidence id;
- записи сохраняют нейтральную форму `agent-adapter-event.v1`;
- решения runner используют validated event summaries и не разбирают provider-specific event names или host stream formats.

Runner не должен зависеть от hook или формата потока одного host.

## Качество review

Structured review и multi-review contracts находятся в `review_mesh/*`. Runner сохраняет только выбранный переход и evidence ids. Workflow adoption, implementation audit и finalization могут применять review-mesh quorum через `workflow/review_mesh_gate.py`, если frozen plan явно включил его. Полные review artifacts остаются authority для review более крупной моделью и final audit.

## За пределами задачи

- Нет фонового daemon.
- Нет отдельного task scheduler product UI.
- Нет provider-specific execution loop в core.
- Нет зависимости от database или long-running server.
