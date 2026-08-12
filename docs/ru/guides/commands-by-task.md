# Команды по задачам

Используйте эту страницу после [первого запуска](install-and-first-run.md).
В примерах указан `<adapter-id>`, поэтому один и тот же маршрут подходит для
любого встроенного адаптера. Команда внешнего инструмента и настройки модели
описаны на странице конкретного адаптера.

## Проверка среды

```
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
agent-lifecycle adapter validate --descriptor adapters/<adapter-id>/adapter.descriptor.json
agent-lifecycle adapter inspect --descriptor adapters/<adapter-id>/adapter.descriptor.json
```

Команда `version` показывает активную установку, а `diagnose` проверяет среду
проекта. Проверка адаптера читает его дескриптор, а осмотр показывает заявленные
возможности и не запускает внешний инструмент.

Предварительный план настройки хоста без применения действий оператора:

```
agent-lifecycle adapter install-plan \
  --descriptor adapters/<adapter-id>/adapter.descriptor.json
```

## Подготовка задачи

Используйте Markdown-файл для длинного запроса, критериев приёмки или ссылки на
несколько документов:

```
agent-lifecycle start --adapter <adapter-id> --file task.md
agent-lifecycle start --adapter <adapter-id> --text "Исследовать ошибку в кэше"
```

Выберите режим подготовки, если заранее известен нужный результат:

```
agent-lifecycle start --adapter <adapter-id> --mode research --file research.md
agent-lifecycle start --adapter <adapter-id> --mode plan --file feature.md
agent-lifecycle start --adapter <adapter-id> --mode review --file proposed-plan.md
```

Чтобы импортировать готовую спецификацию или папку с планом в проверяемый
черновик:

```
agent-lifecycle import plan \
  --source specs/checkout/ \
  --dialect openspec \
  --out work/imports/checkout.json
```

Поддерживаются диалекты `openspec`, `spec-kit`, `bmad` и `spec-kitty`.
Импорт создаёт контекст для нового плана ALK и сам по себе не разрешает
реализацию.

## Проверка плана

Перед заморозкой выполните все проверки плана:

```
agent-lifecycle plan check \
  --manifest tasks/release-<version>/plan.manifest.json \
  --lock tasks/release-<version>/plan.lock.json
agent-lifecycle plan acceptance-check \
  --manifest tasks/release-<version>/plan.manifest.json
agent-lifecycle plan refs-check \
  --manifest tasks/release-<version>/plan.manifest.json
agent-lifecycle plan completeness-check \
  --manifest tasks/release-<version>/plan.manifest.json
```

Зафиксированные манифест и lock-файл связывают требования, владельцев,
разрешённые изменения, критерии приёмки, команды проверки и маршруты
подтверждений. Решение о готовности перед реализацией принимает независимый
аудит плана.

## Реализация зафиксированной задачи

Сначала исходная задача превращается в проверенную спецификацию и план.
Реализация запускается только по структурированному запросу зафиксированной
задачи:

```
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode implement \
  --file work/run/adapter-run-request.json
```

Для выполнения с учётом риска сначала создайте профиль:

```
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode implement \
  --risk auto \
  --risk-profile-out work/risk-profile.json \
  --file work/run/adapter-run-request.json

agent-lifecycle workflow task-start \
  --risk-profile work/risk-profile.json
```

Профиль выбирает нейтральный к провайдеру маршрут модели, ограничения по
токенам и времени и подтверждения использования для заявленного уровня риска.
Он не выбирает провайдера внешнего инструмента и не обходится стороной
зафиксированный план.

Возобновление управляемой ALK-сессии выполняется с проверкой её связей:

```
agent-lifecycle start \
  --adapter <adapter-id> \
  --resume <session-id> \
  --session-root .alk/adapter-sessions
```

## Проверка изменений

Для локального diff:

```
git diff --stat
git diff -- src/ tests/
agent-lifecycle start \
  --adapter <adapter-id> \
  --mode review \
  --file review-request.md
```

Для плана и пакета реализации:

```
agent-lifecycle audit package \
  --plan-dir tasks/release-<version> \
  --state work/state.json \
  --base main \
  --require-frozen \
  --require-implementation \
  --strict \
  --out work/evidence/implementation-audit.json
```

Для изменений в GitHub или GitLab выгрузите в рабочее дерево проверяемый diff и
метаданные изменённых файлов, затем передайте запрос на ревью и пути к
подтверждениям в тот же маршрут. Источником pull request или merge request
остаётся удалённый сервис, а ALK проверяет заявленный план и подтверждения.

## Проверка несколькими моделями ИИ

Review Mesh необязателен и по умолчанию выключен. Можно использовать любые
сочетания доступных адаптеров и моделей; обязательной пары провайдеров нет.
Если доступна только одна модель, используйте обычный маршрут проверки.

```
agent-lifecycle review-mesh recommend \
  --file review-request.md \
  --out work/review-mesh/recommendation.json

agent-lifecycle review-mesh profile \
  --profile-id rm-review \
  --default-mode parallel-research-synthesis \
  --reviewer-model-class strong-reasoning \
  --reviewer-model-class local-strong-review \
  --out work/review-mesh/profile.json

agent-lifecycle review-mesh prepare \
  --intake work/review-mesh/intake.json \
  --template parallel-research-synthesis \
  --profile-id rm-review \
  --phase plan-review \
  --reviewer reviewer-a \
  --reviewer reviewer-b \
  --out-dir work/review-mesh/assignments \
  --out work/review-mesh/prepare.json

agent-lifecycle review-mesh assign \
  --intake work/review-mesh/intake.json \
  --profile work/review-mesh/profile.json \
  --mode parallel-research-synthesis \
  --phase plan-review \
  --assignment-id RM-1 \
  --reviewer-id reviewer-a \
  --out work/review-mesh/assignment-a.json
agent-lifecycle review-mesh import-result \
  --profile work/review-mesh/profile.json \
  --assignment work/review-mesh/assignment-a.json \
  --reviewer-output work/review-mesh/reviewer-a.json \
  --out work/review-mesh/result-a.json
agent-lifecycle review-mesh synthesize \
  --profile work/review-mesh/profile.json \
  --result work/review-mesh/result-a.json \
  --result work/review-mesh/result-b.json \
  --out work/review-mesh/synthesis.json
agent-lifecycle review-mesh quorum \
  --profile work/review-mesh/profile.json \
  --synthesis work/review-mesh/synthesis.json \
  --min-reviewers 2 \
  --out work/review-mesh/quorum.json
```

Внешние инструменты запускают выбранные адаптеры и модели. ALK сохраняет
нейтральные идентификаторы, бюджеты, результаты, статус редактирования и
подтверждение кворума.

## Профиль проекта

```
agent-lifecycle project profile init \
  --adapter <adapter-id> \
  --out .alk/project-profile.json
agent-lifecycle project profile check
```

Профиль хранит локальные значения по умолчанию. Зафиксированный план остаётся
главным источником для риска, границ изменений, обязательных проверок и
приёмки.

## Просмотр прогресса и контекста

```
agent-lifecycle report progress --state work/state.json --terminal
agent-lifecycle report progress --state work/state.json --watch --terminal
agent-lifecycle report status-view --state work/state.json
agent-lifecycle context check --state work/state.json
agent-lifecycle goal check --state work/state.json
agent-lifecycle goal summarize --state work/state.json
```

Эти команды только читают состояние и строят его представление. Модель они не
вызывают.

## Проверка релиза и безопасности

```
agent-lifecycle-neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --require-zero-findings
agent-lifecycle-neutrality scan \
  --scope tracked-release \
  --policy policy/neutrality.policy.json \
  --include-local-artifacts \
  --require-zero-findings
python tools/release/validate_publication_versions.py \
  --target-version <version> \
  --target-ref v<version> \
  --evidence work/evidence/publication-versions.json
agent-lifecycle benchmark evaluate \
  --manifest benchmarks/reference-tasks/manifest.json \
  --out work/evaluation/reference-task-results.json
```

Используйте `--tracked-release` для доказательств публикации, а
`--include-local-artifacts`, если локальный сгенерированный артефакт намеренно
включён в проверку.
