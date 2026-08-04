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

Если нужен текст для терминала вместо JSON, используйте явный флаг:

```bash
agent-lifecycle report progress --state <workflow-state.json> --terminal
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

## Отображение прогресса для адаптеров

`agent-progress-bridge-receipt.v1` упаковывает ту же проекцию прогресса для
обёрток адаптеров. Он фиксирует adapter id, уровень поддержки прогресса, hook
point, строки для терминала и отпечаток исходного progress view или watch
receipt.

```bash
agent-lifecycle report progress-bridge \
  --adapter <adapter-id> \
  --support-level WATCH \
  --hook-point side-terminal-watch \
  --state <workflow-state.json>
```

Bridge только отображает данные: он не является источником правды, не разбирает
host-specific telemetry в core, не вычисляет токены самостоятельно и не
запускает модель.
