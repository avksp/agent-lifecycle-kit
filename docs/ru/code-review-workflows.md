# Сценарии проверки кода

Используйте ALK для проверки кода, когда важно не только посмотреть файл изменений, но и
понять, соответствует ли изменение задаче, архитектуре, подтверждениям и
границам релиза. ALK подходит для локального файла изменений, запроса на
слияние в GitHub, запроса на слияние в GitLab, пакета Markdown с планом и результата задачи,
выполненной по зафиксированному плану.

ALK не обязан сам подключаться к GitHub или GitLab. Подготовьте файл изменений и контекст
обычными командами Git или CLI хоста, затем передайте один Markdown-файл в
`adapter task start`. Обычный текст и Markdown остаются черновым входом для
проверки: они не разрешают реализацию.

## Как выбрать путь

| Случай | Что делать | Основные команды |
| --- | --- | --- |
| Архитектура описана | Проверить файл изменений против архитектуры и контрактов. | `adapter task start`, при необходимости `review-mesh recommend` |
| Архитектура не описана | Сначала восстановить границы архитектуры, затем проверить файл изменений. | `adapter task start`, `review-mesh recommend` |
| Запрос на слияние в GitHub | Получить ветку PR, сохранить файл изменений, проверить этот пакет. | `gh pr checkout` или `git fetch`, затем `adapter task start` |
| Запрос на слияние в GitLab | Получить ветку MR, сохранить файл изменений, проверить этот пакет. | `git fetch`, затем `adapter task start` |
| Только пакет плана | Проверить Markdown-файлы плана без реализации. | `adapter task start`, `review-mesh recommend` |
| Завершённая задача ALK | Проверить результат против зафиксированного плана и подтверждений. | `audit implementation` |
| Высокий риск | Подключить несколько проверяющих; кворум делать обязательным только через зафиксированный план. | `review-mesh assign/import-result/synthesize/quorum` |

## Подготовка пакета проверки

Пакет должен быть явным. В одном Markdown-файле укажите задачу, путь к файлу изменений,
ссылки на архитектуру, область риска и формат результата.

```bash
mkdir -p work/code-review/pr-123
```

Пример файла задачи:

```markdown
# Задача

Проведи проверку изменений из `work/code-review/pr-123/diff.patch`.
Реализацию не начинать.

Архитектура и контракты:
- docs/architecture.md
- docs/reference/public-contracts.md

Проверить:
- соответствие архитектуре и границы модулей;
- ошибки логики и крайние случаи;
- безопасность и обработку данных;
- SOLID, DRY и KISS;
- полноту тестов и недостающие подтверждения;
- риски миграций, совместимости и релиза.

Результат:
- находки по уровню серьёзности;
- что блокирует слияние;
- что можно вынести в последующую задачу;
- какие проверки нужно выполнить.
```

Передайте задачу в ALK:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/pr-123/review-task.md \
  --out work/code-review/pr-123/intake.json
```

Проверьте, нужна ли группа проверяющих:

```bash
agent-lifecycle review-mesh recommend \
  --intake work/code-review/pr-123/intake.json \
  --out work/code-review/pr-123/recommendation.json
```

Рекомендация остаётся советом, пока проверенный зафиксированный план явно не
требует такую проверку.

## Проверка запроса на слияние в GitHub

Если установлен GitHub CLI:

```bash
gh pr checkout 123
mkdir -p work/code-review/pr-123
git diff origin/main...HEAD > work/code-review/pr-123/diff.patch
```

Без GitHub CLI:

```bash
git fetch origin pull/123/head:review/pr-123
mkdir -p work/code-review/pr-123
git diff origin/main...review/pr-123 > work/code-review/pr-123/diff.patch
```

Затем создайте `work/code-review/pr-123/review-task.md` и запустите:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/pr-123/review-task.md \
  --out work/code-review/pr-123/intake.json
```

Такой путь подходит для обычной проверки PR, архитектурной проверки, проверки
безопасности и оценки риска перед слиянием. Не добавляйте в файл задачи секреты и
значения приватных переменных окружения.

## Проверка запроса на слияние в GitLab

Получите ветку MR и подготовьте такой же пакет:

```bash
git fetch origin merge-requests/45/head:review/mr-45
mkdir -p work/code-review/mr-45
git diff origin/main...review/mr-45 > work/code-review/mr-45/diff.patch
```

Создайте `work/code-review/mr-45/review-task.md`:

```markdown
# Задача

Проведи проверку запроса на слияние GitLab 45 по файлу
`work/code-review/mr-45/diff.patch`. Реализацию не начинать.

Проверить архитектуру, дефекты, безопасность, тесты, владение файлами и
релизный риск. Сначала вернуть находки, затем итоговый вердикт по слиянию.
```

Запустите приём задачи и рекомендацию:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/mr-45/review-task.md \
  --out work/code-review/mr-45/intake.json

agent-lifecycle review-mesh recommend \
  --intake work/code-review/mr-45/intake.json \
  --out work/code-review/mr-45/recommendation.json
```

В некоторых установках GitLab могут отличаться имя основной ветки или refspec.
Это остаётся вне ALK; для проверки нужен стабильный файл изменений и понятный контекст
задачи.

## Если архитектура описана

Когда архитектура есть, сделайте её источником правды для проверки:

```markdown
# Задача

Проведи проверку `work/code-review/pr-123/diff.patch` против описанной
архитектуры. Реализацию не начинать.

Архитектура:
- docs/architecture/modular-controller.md
- docs/reference/source-of-truth.md
- docs/reference/public-contracts.md

Фокус:
- изменены ли файлы правильного слоя;
- оправданы ли новые абстракции;
- остаются ли контракты совместимыми;
- доказывают ли тесты нужное поведение;
- не расширены ли заявления релиза или адаптеров.
```

Такой путь лучше использовать для кода, который затрагивает архитектуру,
публичные контракты, адаптеры, безопасность, миграции и релизы.

## Если архитектура не описана

Если архитектура не описана, не нужно делать вид, что проверяющий уже знает
границы системы. Сначала запросите восстановление архитектурной картины:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --text "Проанализируй репозиторий и файл изменений work/code-review/pr-123/diff.patch. Сначала восстанови ответственность модулей и границы архитектуры, затем проверь изменение относительно этой картины. Реализацию не начинать." \
  --out work/code-review/pr-123/intake.json
```

Ожидаемый результат:

- краткая карта архитектуры;
- спорные или непроверенные предположения;
- находки по изменению;
- недостающие тесты или подтверждения;
- нужна ли формальная подготовка плана до реализации.

Для больших или рискованных изменений полезен режим параллельного исследования:
несколько проверяющих независимо восстанавливают архитектуру, а затем ALK
объединяет выводы.

## Проверка Markdown-пакета плана

Если план разложен по нескольким Markdown-файлам, можно дать ссылку на папку
или собрать файлы в один входной пакет.

Если сначала нужно получить детерминированное подтверждение импорта, используйте
импорт папки Markdown:

```bash
agent-lifecycle import plan \
  --source tasks/release-1-40/ \
  --dialect spec-kit \
  --out work/code-review/plan-import.json
```

Проверка внутри того же репозитория:

```bash
cat > work/code-review/plan-review-task.md <<'EOF'
# Задача

Проверь Markdown-пакет плана в `tasks/release-1-40/`.
Прочитай все `.md` файлы в этой папке.
Реализацию не начинать.

Проверить требования, критерии приёмки, маршруты подтверждений, владение
файлами, проверки безопасности и релизные заявления.
EOF

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/plan-review-task.md \
  --out work/code-review/plan-intake.json
```

Переносимый пакет:

```bash
mkdir -p work/code-review
{
  printf '# Задача\n\n'
  printf 'Проверь объединённый Markdown-пакет плана. Реализацию не начинать.\n\n'
  find tasks/release-1-40 -maxdepth 1 -name '*.md' -print | sort | while IFS= read -r file; do
    printf '\n\n---\n\n## %s\n\n' "$file"
    cat "$file"
  done
} > work/code-review/plan-review-input.md

agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/plan-review-input.md \
  --out work/code-review/plan-intake.json
```

## Несколько проверяющих

Создайте профиль:

```bash
agent-lifecycle review-mesh profile \
  --profile-id rm-code-review \
  --default-mode leader-draft-multi-review \
  --reviewer-model-class strong-reasoning \
  --reviewer-model-class local-strong-review \
  --max-invocations 3 \
  --max-input-tokens 12000 \
  --max-output-tokens 3000 \
  --max-wall-seconds 900 \
  --out work/code-review/rm-profile.json
```

Создайте назначения:

```bash
agent-lifecycle review-mesh assign \
  --intake work/code-review/pr-123/intake.json \
  --profile work/code-review/rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-CODEX \
  --reviewer-id codex-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-model-class strong-reasoning \
  --out work/code-review/rm-codex.json

agent-lifecycle review-mesh assign \
  --intake work/code-review/pr-123/intake.json \
  --profile work/code-review/rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-CLAUDE \
  --reviewer-id claude-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-model-class strong-reasoning \
  --out work/code-review/rm-claude.json

agent-lifecycle review-mesh assign \
  --intake work/code-review/pr-123/intake.json \
  --profile work/code-review/rm-profile.json \
  --mode leader-draft-multi-review \
  --phase plan-review \
  --assignment-id RM-OPENCODE \
  --reviewer-id opencode-glm-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-model-class strong-reasoning \
  --out work/code-review/rm-opencode.json
```

Запустите проверяющих вне ALK. Команды ниже являются примерами; замените
идентификаторы моделей на те, которые настроены в вашем CLI:

```bash
codex exec --model <codex-model-id> \
  "Проверь work/code-review/rm-codex.json и верни только JSON reviewer-output.v1" \
  > work/code-review/codex-output.json

claude --model <claude-model-alias> --print --output-format json \
  "Проверь work/code-review/rm-claude.json и верни только JSON reviewer-output.v1" \
  > work/code-review/claude-output.json

opencode run --model <provider>/<model-id> --format json \
  --file work/code-review/rm-opencode.json \
  "Проверь назначение и верни только JSON reviewer-output.v1" \
  > work/code-review/opencode-output.json
```

Для OpenCode `<provider>/<model-id>` может указывать на GLM или любую другую
настроенную модель. ALK оставляет переносимый контракт независимым от
провайдера; конкретная модель выбирается командой хоста или локальной
настройкой хоста.

Каждый проверяющий возвращает небольшой JSON:

```json
{
  "schemaVersion": "reviewer-output.v1",
  "status": "FAIL",
  "budgetUsage": {
    "invocations": 1,
    "inputTokens": 9000,
    "outputTokens": 1400,
    "wallSeconds": 360
  },
  "findings": [
    {
      "id": "CR-1",
      "severity": "MEDIUM",
      "status": "open",
      "message": "Изменение затрагивает границу сессии без регрессионного теста."
    }
  ]
}
```

Импортируйте и объедините результаты:

```bash
agent-lifecycle review-mesh import-result \
  --profile work/code-review/rm-profile.json \
  --assignment work/code-review/rm-codex.json \
  --reviewer-output work/code-review/codex-output.json \
  --out work/code-review/rm-result-codex.json

agent-lifecycle review-mesh import-result \
  --profile work/code-review/rm-profile.json \
  --assignment work/code-review/rm-claude.json \
  --reviewer-output work/code-review/claude-output.json \
  --out work/code-review/rm-result-claude.json

agent-lifecycle review-mesh import-result \
  --profile work/code-review/rm-profile.json \
  --assignment work/code-review/rm-opencode.json \
  --reviewer-output work/code-review/opencode-output.json \
  --out work/code-review/rm-result-opencode.json

agent-lifecycle review-mesh synthesize \
  --profile work/code-review/rm-profile.json \
  --result work/code-review/rm-result-codex.json \
  --result work/code-review/rm-result-claude.json \
  --result work/code-review/rm-result-opencode.json \
  --out work/code-review/rm-synthesis.json

agent-lifecycle review-mesh quorum \
  --profile work/code-review/rm-profile.json \
  --synthesis work/code-review/rm-synthesis.json \
  --min-reviewers 2 \
  --required-role code-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-role code-reviewer \
  --reviewer-role code-reviewer \
  --out work/code-review/rm-quorum.json
```

## Аудит реализации ALK

Если изменение было сделано по зафиксированному плану ALK, используйте аудит
реализации вместо обычной проверки файла изменений:

```bash
agent-lifecycle audit implementation \
  --manifest tasks/release-x/plan.manifest.json \
  --state work/run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --review-mesh-quorum work/code-review/rm-quorum.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

Используйте `--review-mesh-quorum` только если зафиксированный план требует
нескольких проверяющих на этом этапе. В остальных случаях достаточно обычной
независимой проверки задачи.

## Правила безопасности

- Не добавляйте в файлы задачи и вывод проверяющих токены, API-ключи и
  приватные файлы окружения.
- В переносимых пакетах проверки используйте относительные пути репозитория.
- Используйте `--allow-local-evidence-ref` только если зафиксированный план
  явно разрешает ссылки на локальные подтверждения.
- Считайте `review-mesh recommend` советом, пока зафиксированный план явно не
  включил этот режим.
- Не принимайте изменение по самопроверке. Для рискованных изменений нужна
  независимая проверка или зафиксированное подтверждение кворума.
