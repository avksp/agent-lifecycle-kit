# Read-only status views

Read-only status views — компактные рабочие представления поверх уже
существующих артефактов. Они не являются source of truth, не пишут workflow
state, не запускают host code и не тратят токены на модельные вызовы.

## Status view

`agent-readonly-status-view.v1` показывает digest исходных артефактов, статус,
blocker codes и следующие действия.

```bash
agent-lifecycle report status-view --artifact <evidence.json> --target-window 4k-strict
```

## Event feed

`agent-workflow-event-feed.v1` строит детерминированный список событий из
`agent-workflow-state.v3`. Workflow state остаётся источником правды.

```bash
agent-lifecycle report event-feed --state <workflow-state.json>
```

## Lifecycle progress

`agent-lifecycle-progress-view.v1` выводит lifecycle шаги в одну строку:
status, `hh:mm:ss`, `↑out/↓in tok` и краткий git-style счётчик изменений.
Если usage receipt не attested, токены показываются как `↑?/↓? tok`.

```text
implementation         DONE       00:01:05 ↑0.2k/↓1.1k tok 7 files · +432 -118
TOTAL                  DONE       00:01:05 ↑0.2k/↓1.1k tok 7 files changed · 432 insertions · 118 deletions · 5 modified · 1 added · 1 deleted
```
