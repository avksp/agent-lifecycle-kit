# Представления статуса без записи

Представления статуса без записи — компактные рабочие представления поверх уже
существующих артефактов. Они не являются источником правды, не меняют состояние
рабочего цикла, не запускают код хоста и не тратят токены на модельные вызовы.

## Представление статуса

`agent-readonly-status-view.v1` показывает отпечатки исходных артефактов,
статус, коды блокеров и следующие действия.

```bash
agent-lifecycle report status-view --artifact <evidence.json> --target-window 4k-strict
```

## Лента событий

`agent-workflow-event-feed.v1` строит детерминированный список событий из
`agent-workflow-state.v3`. Состояние рабочего цикла остаётся источником правды.

```bash
agent-lifecycle report event-feed --state <workflow-state.json>
```

## Прогресс жизненного цикла

`agent-lifecycle-progress-view.v1` выводит шаги жизненного цикла в одну строку:
статус, `hh:mm:ss`, `↑out/↓in tok` и краткий счётчик изменений в стиле Git.
Если артефакт использования не подтверждён, токены показываются как
`↑?/↓? tok`.

```text
implementation         DONE       00:01:05 ↑0.2k/↓1.1k tok 7 files · +432 -118
TOTAL                  DONE       00:01:05 ↑0.2k/↓1.1k tok 7 files changed · 432 insertions · 118 deletions · 5 modified · 1 added · 1 deleted
```

Для отображения прогресса во время работы используйте ограниченный режим
наблюдения. Он повторно читает те же локальные артефакты и возвращает
`agent-lifecycle-progress-watch.v1`; состояние жизненного цикла не меняется,
модель не вызывается.

```bash
agent-lifecycle report progress --state <workflow-state.json> \
  --watch \
  --watch-iterations 10 \
  --watch-interval 1
```

Счётчик изменений формируется отдельной командой. Она считает изменения в
отслеживаемом Git diff и создаёт `agent-change-summary-receipt.v1`, который
затем можно передать в прогресс:

```bash
agent-lifecycle report change-summary \
  --project-root . \
  --base <start-revision> \
  --out work/run/change-summary.json
```
