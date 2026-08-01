# Issue to specification drafts

Внешние issue, тикеты и payloads трекеров являются входом для анализа, а не
разрешением на выполнение. Skill `issue-to-spec` переводит такой вход в
draft-only ALK specification input.

Результат должен сохранять:

- `sourceTrusted: false`
- `requiresReview: true`
- `freezeBlocked: true`
- `executionAuthorized: false`

Draft фиксирует source issue ids, candidate requirements, acceptance checks,
ограничения, риски, недостающие evidence и вопросы, которые блокируют freeze.
После этого он проходит обычный путь через `agent-first-planning` и
`audit-agent-plan`.

Если issue описывает дефект, draft может рекомендовать optional Bug Forensics
profile, но reproduction и repair evidence всё равно принадлежат проверенному
плану.
