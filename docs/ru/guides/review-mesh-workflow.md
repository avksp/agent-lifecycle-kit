# Проверка несколькими моделями через Review Mesh

Review Mesh помогает независимо проверить исследование, план или реализацию.
Участники могут использовать разные адаптеры и модели: например Codex, Claude
Code или OpenCode. ALK готовит назначения, импортирует ответы, объединяет находки
и проверяет кворум. Модели запускает оператор или обёртка хоста; ALK не становится
посредником провайдеров и сам не запускает CLI проверяющих.

Review Mesh необязателен и выключен по умолчанию. Для обычной задачи с низким
риском достаточно стандартного жизненного цикла с одним независимым проверяющим.
Несколько сессий одной модели не доказывают независимость, если профиль требует
различий и по `host`, и по `model`. Примеры ниже не задают постоянный состав:
допустимы доступные хосты и локальные модели.

После нескольких настоящих проверок [оптимизация аудита по доказательствам](../reference/audit-optimization.md)
может обобщить качество, ожидание, токены и ресурсы. Это рекомендация: изменение
будущего профиля требует контрольной проверки качества и явного одобрения.

## Выбрать сценарий

| Задача | Режим и результат |
| --- | --- |
| Исследование или план | `parallel-research-synthesis`; остановиться после синтеза или кворума, без полномочий на реализацию. |
| Проверить черновик ведущего | `leader-draft-multi-review`; проверить границы, владение файлами, откат, доказательства и риск выпуска. |
| Исследовать ошибку | Начать с `adapter task start --file bug.md`; Bug Forensics может быть рекомендован. Исходный текст ошибки не разрешает исправления. |
| Аудит результата задачи | `implementation-audit-panel`; проверить критерии приёмки, изменённые файлы, свежесть доказательств и побочные последствия. |
| Финальная проверка безопасности или релиза | Только по зафиксированному плану; проверить заявления релиза, секреты, локальные пути, поддержку хостов, откат и пробелы доказательств. |

Для малого контекста разделите назначения по этапам, оставьте пакеты компактными
и используйте нейтральные идентификаторы. Синтез сохраняет общие выводы и пробелы.
Краткие сценарии см. в [сценариях жизненного цикла](lifecycle-cookbook.md).

## Получить рекомендацию без запуска реализации

Создайте файл задачи. В примере требуется только исследование и план.

```markdown
# Task

Research the current adapter session flow and write a plan for improving
resume behavior. Do not implement yet.
```

Примите файл через выбранный адаптер. Эта команда не начинает реализацию.

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file task.md \
  --out intake.json
```

Запросите рекомендацию Review Mesh.

```bash
agent-lifecycle review-mesh recommend \
  --intake intake.json \
  --out review-mesh-recommendation.json
```

При результате `off` продолжайте обычный цикл. Режимы
`leader-draft-multi-review`, `parallel-research-synthesis` и
`implementation-audit-panel` становятся обязательными только после явного
включения в проверенный и зафиксированный план.

## Подготовить назначения одной командой

Команда `prepare` создаёт локальный профиль и пакет для каждого проверяющего.
Идентификаторы в примере заменяемы; конкретную модель выбирает CLI хоста.

```bash
agent-lifecycle review-mesh prepare \
  --intake intake.json \
  --template parallel-research-synthesis \
  --reviewer codex-example:architecture-reviewer:strong-reasoning \
  --reviewer claude-example:risk-reviewer:strong-reasoning \
  --reviewer opencode-glm-example:local-reviewer:local-strong-review \
  --evidence-id EV-PLAN \
  --out-dir work/review-mesh/plan-review \
  --out work/review-mesh/prepare-receipt.json
```

Команда записывает `profile.json`, файлы `assignments/` и отдельный receipt
в указанный каталог. ALK хранит нейтральные классы `strong-reasoning` и
`local-strong-review`, а не переносимые названия моделей провайдера.

Для OpenCode сначала проверьте `opencode models <provider>`, затем передайте
тот же `<provider>/<model-id>` в `--model`. GLM-5.2 — только пример настроенной
модели; при необходимости выберите другую. Для каждого вызова задайте отдельный
заголовок. Команды 1.x и 2.x различаются наличием `--standalone`.

```bash
opencode models <provider>
# OpenCode 1.x: bounded invocation; unique title per call.
python3 -c 'import subprocess,sys; subprocess.run(sys.argv[1:],check=True,timeout=120)' \
  opencode run "Review the assignment and return only reviewer-output.v1 JSON" \
  --model "<provider>/<model-id>" --format=json \
  --title "alk-review-$(python3 -c 'import uuid; print(uuid.uuid4())')" \
  --file="work/review-mesh/plan-review/assignments/parallel-research-synthesis-3.json" \
  > reviewer-glm-output.json

# OpenCode 2.x: bounded invocation; unique title per call.
python3 -c 'import subprocess,sys; subprocess.run(sys.argv[1:],check=True,timeout=120)' \
  opencode run "Review the assignment and return only reviewer-output.v1 JSON" \
  --model "<provider>/<model-id>" --format=json --standalone \
  --title "alk-review-$(python3 -c 'import uuid; print(uuid.uuid4())')" \
  --file="work/review-mesh/plan-review/assignments/parallel-research-synthesis-3.json" \
  > reviewer-glm-output.json
```

### Один файл Markdown

Передайте один подготовленный файл с задачей, ограничениями и ожидаемым ответом.

```markdown
# Task

Review the current managed adapter session flow and write an improvement plan.
Do not implement yet.

Check:
- lifecycle completeness;
- safe resume behavior;
- whether the plan avoids creating a second agent runtime.
```

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file tasks/review/adapter-sessions.md \
  --out intake.json

agent-lifecycle review-mesh recommend \
  --intake intake.json \
  --out review-recommendation.json
```

### Каталог планов

`--file` принимает один файл, а не каталог. Когда проверяющие имеют тот же
репозиторий, подготовьте задачу, которая явно указывает каталог и нужные файлы.

```bash
cat > task.md <<'EOF'
# Task

Review the Markdown plan package in `tasks/release-1-40/`.
Read every `.md` file in that directory.

Focus on:
- requirements and acceptance criteria;
- evidence and validation commands;
- file ownership;
- security and release risks.

Do not implement. Return only findings and a final recommendation.
EOF

agent-lifecycle adapter task start --adapter codex --file task.md --out intake.json
agent-lifecycle review-mesh recommend --intake intake.json --out review-recommendation.json
```

Для переносимого пакета без доступа к репозиторию объедините Markdown-файлы
в один вход в устойчивом порядке. Пример готовит вход, но не запускает модель.

```bash
mkdir -p work/group-review
{
  printf '# Task\n\n'
  printf 'Review the combined Markdown plan package. Do not implement.\n\n'
  find tasks/release-1-40 -maxdepth 1 -name '*.md' -print | sort | while IFS= read -r file; do
    printf '\n\n---\n\n## %s\n\n' "$file"
    cat "$file"
  done
} > work/group-review/plan-review-input.md

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/group-review/plan-review-input.md \
  --out intake.json

agent-lifecycle review-mesh recommend \
  --intake intake.json \
  --out review-recommendation.json
```

## Вручную подготовить небольшую группу

Профиль задаёт ограничения вызовов, токенов и времени, а также нейтральные
требования независимости.

```bash
agent-lifecycle review-mesh profile \
  --profile-id rm-plan-review \
  --default-mode leader-draft-multi-review \
  --reviewer-model-class strong-reasoning \
  --reviewer-model-class local-strong-review \
  --max-invocations 3 \
  --max-input-tokens 12000 \
  --max-output-tokens 3000 \
  --max-wall-seconds 900 \
  --out rm-profile.json
```

Создайте отдельное назначение для каждого проверяющего. Идентификаторы
`reviewer-a` и `reviewer-b` — примеры, а не названия провайдеров или моделей.

```bash
agent-lifecycle review-mesh assign \
  --intake intake.json \
  --profile rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-PLAN-A \
  --reviewer-id reviewer-a \
  --reviewer-role plan-reviewer \
  --reviewer-model-class strong-reasoning \
  --out rm-assignment-a.json

agent-lifecycle review-mesh assign \
  --intake intake.json \
  --profile rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-PLAN-B \
  --reviewer-id reviewer-b \
  --reviewer-role plan-reviewer \
  --reviewer-model-class local-strong-review \
  --out rm-assignment-b.json
```

### Запустить проверяющих средствами хостов

Конкретная модель задаётся локальной конфигурацией хоста или явным флагом.
ALK сохраняет нейтральные классы и при необходимости отпечатки идентичности.
Следующие команды выполняет оператор, а не Review Mesh.

```bash
codex exec --model <codex-model-id> \
  "Review rm-assignment-a.json and return only reviewer-output.v1 JSON" \
  > reviewer-a-output.json

claude --model <claude-model-alias> --print --output-format json \
  "Review rm-assignment-b.json and return only reviewer-output.v1 JSON" \
  > reviewer-b-output.json

opencode models <provider>
# OpenCode 1.x: bounded invocation; unique title per call.
python3 -c 'import subprocess,sys; subprocess.run(sys.argv[1:],check=True,timeout=120)' \
  opencode run "Review the assignment and return only reviewer-output.v1 JSON" \
  --model "<provider>/<model-id>" --format=json \
  --title "alk-review-$(python3 -c 'import uuid; print(uuid.uuid4())')" \
  --file="rm-assignment-glm.json" \
  > reviewer-glm-output.json

# OpenCode 2.x: bounded invocation; unique title per call.
python3 -c 'import subprocess,sys; subprocess.run(sys.argv[1:],check=True,timeout=120)' \
  opencode run "Review the assignment and return only reviewer-output.v1 JSON" \
  --model "<provider>/<model-id>" --format=json --standalone \
  --title "alk-review-$(python3 -c 'import uuid; print(uuid.uuid4())')" \
  --file="rm-assignment-glm.json" \
  > reviewer-glm-output.json
```

Если зафиксированный план требует доказательств независимости, передайте
нейтральный отпечаток в назначение. Исходное имя модели храните в локальных
заметках хоста. `MODEL_ID` ниже — пример OpenCode/GLM; замените его на модель,
поддерживаемую выбранным CLI, включая Codex, Claude, Qwen или локальный хост.

```bash
MODEL_ID='<provider>/glm-5.2'
MODEL_HASH=$(printf '%s' "opencode:${MODEL_ID}" | shasum -a 256 | cut -d ' ' -f 1)

agent-lifecycle review-mesh assign \
  --intake intake.json \
  --profile rm-profile.json \
  --mode parallel-research-synthesis \
  --phase plan-review \
  --assignment-id RM-GLM \
  --reviewer-id opencode-glm-reviewer \
  --reviewer-role plan-reviewer \
  --reviewer-model-class strong-reasoning \
  --reviewer-model-identity-hash "$MODEL_HASH" \
  --out rm-assignment-glm.json
```

Каждый проверяющий получает свой пакет и возвращает небольшой
`reviewer-output.v1` с находками и фактическим расходом токенов и ресурсов.
Числа в примере — иллюстрация формы, а не измерения текущего запуска.

```json
{
  "schemaVersion": "reviewer-output.v1",
  "status": "FAIL",
  "budgetUsage": {
    "invocations": 1,
    "inputTokens": 12000,
    "outputTokens": 1800,
    "wallSeconds": 420
  },
  "findings": [
    {
      "id": "PLAN-1",
      "severity": "MEDIUM",
      "status": "open",
      "message": "The plan needs an explicit rollback step for failed resume."
    }
  ]
}
```

Импортируйте каждый подлинный ответ. Импорт скрывает маркеры, похожие на
секреты, и отказывает при частных абсолютных путях, если план явно не допускает
локальные ссылки на доказательства.

```bash
agent-lifecycle review-mesh import-result \
  --profile rm-profile.json \
  --assignment rm-assignment-a.json \
  --reviewer-output reviewer-a-output.json \
  --out rm-result-a.json

agent-lifecycle review-mesh import-result \
  --profile rm-profile.json \
  --assignment rm-assignment-b.json \
  --reviewer-output reviewer-b-output.json \
  --out rm-result-b.json
```

Объедините находки.

```bash
agent-lifecycle review-mesh synthesize \
  --profile rm-profile.json \
  --result rm-result-a.json \
  --result rm-result-b.json \
  --out rm-synthesis.json
```

Если ведущий разрешил находку, укажите её идентификатор явно.

```bash
agent-lifecycle review-mesh synthesize \
  --profile rm-profile.json \
  --result rm-result-a.json \
  --result rm-result-b.json \
  --accepted-finding-id PLAN-1 \
  --out rm-synthesis.json
```

Постройте подтверждение кворума. Оно является доказательством и не заменяет
проверку плана, аудит реализации или итоговый proof.

```bash
agent-lifecycle review-mesh quorum \
  --profile rm-profile.json \
  --synthesis rm-synthesis.json \
  --min-reviewers 2 \
  --required-role plan-reviewer \
  --reviewer-role plan-reviewer \
  --reviewer-role plan-reviewer \
  --out rm-quorum.json
```

## Сделать кворум обязательным для выбранных этапов

Review Mesh блокирует процесс только после явного включения в зафиксированный
план. `quorumReceiptPath` используется при принятии на этапе freeze.

```json
{
  "reviewMesh": {
    "required": true,
    "phases": ["freeze", "implementation-audit", "final-audit"],
    "profileDigest": "<profileDigest from rm-profile.json>",
    "quorumReceiptPath": "work/review-mesh/freeze-quorum.json"
  }
}
```

Для аудита реализации и финального этапа передавайте отдельный receipt
соответствующего этапа. Это шаблоны команд, а не разрешение менять реальный запуск.

```bash
agent-lifecycle audit implementation \
  --manifest work/plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --review-mesh-quorum work/review-mesh/implementation-quorum.json \
  --out work/WS-01/attempt-1/implementation-audit.json

agent-lifecycle workflow finalize \
  --state run.state.json \
  --operation-id finalize-op \
  --expected-revision 12 \
  --source-revision "$(git rev-parse HEAD)" \
  --final-audit final/final-audit.json \
  --review-mesh-quorum work/review-mesh/final-quorum.json \
  --proof final/final-proof.json \
  --reason "complete"
```

## Безопасность и завершение

- Рекомендации необязательны, пока проверенный план не сделал этап блокирующим.
- Если независимость или кворум недостижимы, исправьте и повторно зафиксируйте
  план. Не переиспользуйте личности проверяющих для обхода условия.
- ALK не вызывает API провайдера и не запускает CLI проверяющего.
- Переносимые контракты содержат нейтральные идентификаторы и классы моделей.
- Ограничения включают токены, количество вызовов и время.
- В импортируемых ответах не должно быть сырых секретов и частных локальных путей.

Последовательность: `adapter task start` → `recommend` → профиль → назначения →
внешний запуск проверяющих → `import-result` → `synthesize` → `quorum`.
Приложите кворум только к тем этапам, где его требует зафиксированный план.

## Переносимый индекс чтения

Необязательный `review-mesh prepare --review-input <inventory> --repository-root .`
проверяет привязанные к исходникам локальные входы до создания нового каталога.
Передайте каждому проверяющему `reading-index.json`, указанные байты и созданный
контракт сырого ответа. Проверьте доступность клона: локальные или изменённые
входы нужно доставить отдельно. Исходники не встраиваются в промпт; подготовка
не запускает проверяющего и не подтверждает доставку.

Созданные примеры имеют статус SKIPPED и не заменяют настоящий обзор.
Импортируйте фактический `reviewer-output.v1`; не переименовывайте
`agent-review-mesh-result.v1` в сырой ответ. См. [инвентарь, диапазоны и покрытие](../reference/review-mesh.md#bounded-review-handoff).
