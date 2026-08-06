# Групповая проверка

Групповая проверка — это дополнительный слой контрактов для работы с
несколькими проверяющими. Он полезен, когда плану нужно больше одного
независимого взгляда на планирование, исследование или подтверждения
реализации, но не входит в базовый жизненный цикл. Техническое имя команды:
`review-mesh`.

Поддерживаются режимы:

- `leader-draft-multi-review`: один ведущий готовит черновик плана или
  исследования, а независимые проверяющие оценивают результат.
- `parallel-research-synthesis`: несколько проверяющих независимо готовят
  варианты исследования или плана перед объединением результатов.
- `implementation-audit-panel`: несколько аудиторов проверяют подтверждения
  реализации после завершения работы.

Детерминированная рекомендация режима помогает понять, нужна ли такая проверка.
Полуавтоматический слой вокруг неё создаёт назначения проверяющим, импортирует
результаты, объединяет выводы и проверяет кворум. ALK по-прежнему не запускает
адаптеры проверяющих: оператор или обёртка хоста запускает их отдельно и
возвращает подтверждение для импорта.

Версия 1.46 добавляет шаблоны для оператора и команду `review-mesh prepare`.
Команда превращает артефакт приёма задачи, манифест плана или handoff в
локальный профиль, пакеты назначений и `agent-review-mesh-prepare-receipt.v1`.
Проверяющие по-прежнему не запускаются из ALK.

## Стабильные схемы

- `agent-review-mesh-profile.v1`
- `agent-review-mesh-assignment.v1`
- `agent-review-mesh-result.v1`
- `agent-review-mesh-synthesis.v1`
- `agent-review-mesh-quorum-receipt.v1`
- `agent-review-mesh-quorum-validation.v1`
- `agent-review-mesh-recommendation.v1`

## Рекомендация режима

Рекомендация полезна, когда оператор хочет понять, нужна ли дополнительная
проверка до включения её в план:

```bash
agent-lifecycle review-mesh recommend --text "Исследуй архитектуру и составь план"
agent-lifecycle review-mesh recommend --file task.md
agent-lifecycle review-mesh recommend --intake adapter-task-start.json
agent-lifecycle review-mesh recommend --manifest plan.manifest.json
```

Полученный артефакт может рекомендовать `off`, `leader-draft-multi-review`,
`parallel-research-synthesis` или `implementation-audit-panel`. В нём есть
этапы жизненного цикла, причины рекомендации, число проверяющих, лимиты по
токенам и ресурсам, нейтральные классы моделей и причина отказа, если
достаточно обычного жизненного цикла.

Рекомендация не даёт права на выполнение. Она не включает обязательные
контрольные точки, не создаёт назначения, не проверяет кворум, не запускает
модель, не запускает адаптеры и не запускает CLI хоста. Чтобы групповая
проверка стала обязательным подтверждением, это должно быть явно принято в
проверенном зафиксированном плане.

## Шаблоны и подготовка

Список встроенных локальных шаблонов:

```bash
agent-lifecycle review-mesh template-list
```

Текущие шаблоны:

- `leader-draft-review`: пакеты для проверки черновика плана.
- `parallel-research-synthesis`: независимые пакеты исследования перед
  объединением выводов.
- `implementation-audit-panel`: пакеты аудита реализации после появления
  результата и подтверждений.

Команда `prepare` нужна, когда профиль и назначения нужно подготовить одним
шагом:

```bash
agent-lifecycle review-mesh prepare \
  --intake intake.json \
  --template parallel-research-synthesis \
  --reviewer codex-example:architecture-reviewer:strong-reasoning \
  --reviewer claude-example:risk-reviewer:strong-reasoning \
  --reviewer opencode-glm-example:local-reviewer:local-strong-review \
  --out-dir work/review-mesh/plan-review \
  --out work/review-mesh/prepare-receipt.json
```

Идентификаторы проверяющих выше являются примерами. Конкретная модель
выбирается в выбранном CLI, например Codex, Claude Code или OpenCode. В
переносимом артефакте ALK указывайте нейтральные классы моделей:
`strong-reasoning`, `local-strong-review` и другие поддерживаемые классы.

`prepare` записывает `profile.json`, отдельный пакет для каждого проверяющего в
`assignments/` и подтверждение с `hostExecutionStarted: false`,
`modelCallsStarted: false`, `providerBrokerStarted: false`.

## Назначения, результаты, объединение выводов и кворум

После явного включения в проверенном плане ALK может координировать
подтверждения групповой проверки, не становясь посредником для моделей:

```bash
agent-lifecycle review-mesh profile --profile-id rm-profile --out rm-profile.json

agent-lifecycle review-mesh assign --intake adapter-task-start.json \
  --profile rm-profile.json \
  --mode leader-draft-multi-review --phase plan-review \
  --assignment-id RM-1 --reviewer-id claude-reviewer --out rm-assignment.json

agent-lifecycle review-mesh import-result --profile rm-profile.json \
  --assignment rm-assignment.json --reviewer-output reviewer-output.json \
  --out rm-result.json

agent-lifecycle review-mesh synthesize --profile rm-profile.json \
  --result rm-result-a.json --result rm-result-b.json --out rm-synthesis.json

agent-lifecycle review-mesh quorum --profile rm-profile.json \
  --synthesis rm-synthesis.json --min-reviewers 2 --out rm-quorum.json
```

Назначения являются компактными пакетами для выполнения на стороне хоста.
Импорт результатов маскирует признаки секретов и отклоняет локальные абсолютные
пути, если план явно не разрешил ссылки на локальные подтверждения. Объединение
выводов фиксирует совпадения, конфликты, принятые, отклонённые и нерешённые
замечания. Артефакт кворума может блокировать заморозку плана, аудит
реализации или финальный аудит только тогда, когда зафиксированный план требует
групповую проверку для этого этапа.

Пошаговые примеры для частых задач:
[практические сценарии групповой проверки](../review-mesh-workflow.md).

## Правила контракта

Групповая проверка падает закрыто и не зависит от провайдера:

- выключен по умолчанию;
- включается только явным проверенным планом;
- носит рекомендательный характер, пока зафиксированный план не требует
  обязательного режима;
- ограничивается токенами, числом вызовов и временем выполнения;
- не является канонической поверхностью учёта `USD-cost`;
- проверяет независимость по нейтральным `hostIdentityHash` и
  `modelIdentityHash`;
- конкретные имена провайдера, модели и аккаунта не являются переносимыми
  полями идентичности.

Реализация переиспользует существующую семантику дополнительной перепроверки
для бюджетов и независимости. Групповая проверка добавляет режимы жизненного
цикла и артефакты вокруг этих проверок, но не создаёт второй механизм проверки.

## Границы

Групповая проверка не заменяет проверку спецификации, заморозку плана, аудит
реализации и финальное подтверждение. Она добавляет подтверждения только тогда,
когда задача или план явно этого требуют. Запуск CLI, учётные данные
провайдера, выбор модели и выполнение проверяющего остаются в зоне
ответственности адаптера или оператора.
