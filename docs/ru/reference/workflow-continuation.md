# Управляемое продолжение workflow

`agent-lifecycle workflow continue` показывает следующий шаг workflow и может
явно применить один существующий переход. Это сокращённый интерфейс оператора,
а не вторая машина состояний: полномочия остаются у состояния workflow,
зафиксированного плана, lock-файла и валидаторов обычных команд перехода.

## Сначала проекция

По умолчанию команда работает только для чтения:

```bash
agent-lifecycle workflow continue \
  --state work/run.state.json \
  --manifest work/plans/release-x/plan.manifest.json \
  --lock work/plans/release-x/plan.lock.json \
  --operation-id continue-WS-01 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --reason "показать следующий ограниченный шаг"
```

Подтверждение возвращает `READY`, `INPUT_REQUIRED`, `WAITING` или `BLOCKED`,
всегда с `stateWritten: false`, `modelCallsStarted: false` и
`hostLaunchStarted: false`. Поле `requiredInputs` перечисляет точные внешние
артефакты или выбор задачи для текущего маршрута.

## Применение одного перехода

Повторно передайте тот же operation id и тот же набор входов. Значения
`action.stateRevision` и `action.actionDigest` возьмите из проекции:

```bash
agent-lifecycle workflow continue \
  --state work/run.state.json \
  --manifest work/plans/release-x/plan.manifest.json \
  --lock work/plans/release-x/plan.lock.json \
  --operation-id continue-WS-01 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --reason "применить результат независимой проверки" \
  --task WS-01 \
  --review work/WS-01/attempt-1/task-review.json \
  --implementation-audit work/audits/WS-01.json \
  --apply \
  --projected-state-revision 7 \
  --projected-action-digest <action-digest>
```

Успешный вызов возвращает `APPLIED`, увеличивает ревизию состояния ровно на
один и записывает обычное событие переиспользованного перехода. Недостающие
входы дают `INPUT_REQUIRED`; устаревшая связь состояния, действия, плана,
lock-файла, исходной ревизии или артефакта даёт `BLOCKED`. Модель и внешний
инструмент не запускаются.

## Входы

Команда принимает только входы существующих переходов:

- авторизация: `--authorization-receipt`;
- выбор и запуск задачи: `--task`, при необходимости `--risk-profile`;
- результат задачи: `--result`, `--model-usage-receipt`, `--budget-targets`;
- проверка задачи: `--review`, `--implementation-audit`, повторяемый
  `--finding-id`;
- результат финального аудита: `--final-audit`, `--verdict`, повторяемые
  `--task-id` и `--finding-id` для `REWORK`;
- финализация: `--final-audit`, `--proof`, `--proof-integrity`,
  `--goal-record`, `--follow-up-register`, `--completion-gate-receipt`,
  `--final-implementation-audit` и повторяемый `--review-mesh-quorum`.

Все пути должны быть относительными к репозиторию. Переданный вход не
становится доверенным: выбранный переход всё равно проверяет каноническую
форму, lineage, независимость, свежесть, владение и политику до записи.

## Маршруты без записи

Активная работа внешнего инструмента, решение бюджета, внешнее действие,
неразрешённый блокер, завершённый запуск и `PLAN_ONLY` не продвигаются этим
фасадом. Они остаются в `WAITING` или `BLOCKED` с указанием действия владельца.
Для неподдерживаемых действий используйте существующие специальные команды.

Команды `workflow run`, `workflow task-*`, `workflow final-audit-outcome` и
`workflow finalize` остаются поддерживаемыми и вызывают те же сервисы
переходов.
