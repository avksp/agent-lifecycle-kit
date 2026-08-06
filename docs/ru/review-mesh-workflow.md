# Практические сценарии групповой проверки

Этот документ показывает, как использовать групповую проверку без превращения
ALK в посредника для моделей. ALK готовит назначения, импортирует результаты
проверяющих, объединяет выводы и проверяет кворум. Проверяющих запускает
оператор или обёртка хоста. Техническое имя CLI-команды остаётся
`review-mesh`.

Используйте этот сценарий, когда задаче нужна более сильная проверка:

- исследование перед реализацией;
- архитектурный анализ или анализ риска;
- проверка плана несколькими адаптерами;
- аудит реализации несколькими проверяющими;
- рискованные задачи по ошибкам, безопасности или релизу.

Для обычных небольших правок оставляйте базовый жизненный цикл без групповой
проверки.

## Выберите подходящий путь

| Уровень | Когда использовать | Команды |
| --- | --- | --- |
| Начальный | Понять, нужна ли дополнительная проверка | `adapter task start`, `review-mesh recommend` |
| Средний | Провести небольшую группу проверяющих | `recommend`, `assign`, `import-result`, `synthesize`, `quorum` |
| Продвинутый | Встроить групповую проверку в обязательные этапы плана | атомарные команды `review-mesh` и `--review-mesh-quorum` |

## Частые сценарии

### Исследование или план без реализации

Используйте этот сценарий, когда результатом должен быть анализ, архитектурная
записка или план, а не изменение кода. Опишите задачу в Markdown, запустите
`adapter task start --file`, затем `review-mesh recommend`. Если рекомендован
`parallel-research-synthesis`, создайте назначения с
`--mode parallel-research-synthesis --phase plan-review`.

Остановитесь после `review-mesh synthesize` или `review-mesh quorum`. Итоговое
объединение выводов и есть результат работы; реализация не разрешается, пока
отдельный план не будет проверен и зафиксирован.

### Черновик ведущего и независимая проверка

Используйте `leader-draft-multi-review`, когда один адаптер или оператор уже
подготовил план, а два или более проверяющих должны оценить границы задачи,
пропущенные подтверждения, владение файлами, откат и релизные риски. Групповая
проверка хранит пакеты проверки и подтверждения результатов, но решение о
принятии замечаний остаётся за владельцем плана.

### Поиск ошибки или регрессии

Начните с `adapter task start --file bug.md`; приём задачи может отметить
признаки задачи по дефекту. Профиль расследования ошибок может быть рекомендован для
воспроизведения, отпечатка ошибки и подтверждения регрессии. Групповая проверка
полезна вокруг этого профиля: `leader-draft-multi-review` подходит для проверки
первопричины и плана исправления, а `implementation-audit-panel` — после правки
для проверки подтверждений.

Сырой текст с описанием ошибки всё равно не разрешает реализацию. Выполнение
начинается только через обычный проверенный план или зафиксированный запрос на
запуск.

### Аудит реализации несколькими проверяющими

Используйте `implementation-audit-panel`, когда исполнитель уже подготовил
результат задачи и подтверждения. Каждый проверяющий получает назначение,
сфокусированное на критериях приёмки, изменённых файлах, актуальности
подтверждений и риске побочных изменений. Если план требует групповой проверки
на этом этапе, передайте подтверждение кворума:

```bash
agent-lifecycle audit implementation \
  --manifest plans/package/plan.manifest.json \
  --state run.state.json \
  --task WS-01 \
  --result work/WS-01/attempt-1/task-result.json \
  --review work/WS-01/attempt-1/task-review.json \
  --review-mesh-quorum work/review-mesh/implementation-quorum.json \
  --out work/WS-01/attempt-1/implementation-audit.json
```

### Финальная проверка безопасности или релиза

Используйте групповую проверку как финальную проверку высокого риска только
тогда, когда это указано в зафиксированном плане. Проверяющие должны смотреть на
релизные заявления, маскирование секретов, утечки локальных путей,
неподтверждённые заявления об адаптерах, инструкции отката и пробелы в
подтверждениях. Финальное подтверждение кворума можно передать в
`workflow finalize`.

### Работа с маленькими или локальными моделями

Групповая проверка может повышать качество без обязательного перехода на одну
большую модель. Делайте назначения компактными, используйте нейтральные
идентификаторы проверяющих и классы моделей, разделяйте задачу по этапам.
Небольшие модели могут проверять узкие пакеты, а объединение выводов фиксирует
общий результат и нерешённые пробелы.

## Простой путь: только рекомендация

Создайте файл задачи:

```markdown
# Задача

Исследуй текущий процесс сессий адаптеров и составь план улучшения
возобновления. Реализацию пока не начинать.
```

Примите задачу для выбранного адаптера. Это не запускает реализацию:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file task.md \
  --out intake.json
```

Проверьте, нужна ли дополнительная перепроверка:

```bash
agent-lifecycle review-mesh recommend \
  --intake intake.json \
  --out review-mesh-recommendation.json
```

Если рекомендация вернула `off`, продолжайте обычный процесс ALK. Если
рекомендован `leader-draft-multi-review`, `parallel-research-synthesis` или
`implementation-audit-panel`, это всё ещё только совет. Обязательным он станет
только после явного включения в проверенный зафиксированный план.

### Проверить один Markdown-файл с задачей

Когда задача уже записана в Markdown, передайте этот файл как единственный
вход. Например `tasks/review/adapter-sessions.md` может содержать исследование,
запрет на реализацию и ожидаемый формат результата:

```markdown
# Задача

Проверь текущий процесс управляемых сессий адаптеров и составь план улучшения.
Реализацию не начинать.

Нужно проверить:
- полноту жизненного цикла;
- безопасность возобновления;
- что план не вводит второй механизм выполнения для агента.
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

### Проверить папку с несколькими Markdown-файлами

`--file` принимает один подготовленный входной файл. Если план разложен по
нескольким `.md`, есть два безопасных варианта.

Если проверяющие работают в том же репозитории, можно дать задачу со ссылкой на
путь:

```bash
cat > task.md <<'EOF'
# Задача

Проверь Markdown-пакет плана в `tasks/release-1-40/`.
Смотреть все `.md` файлы в этой папке.

Фокус проверки:
- требования и критерии приёмки;
- подтверждения и команды проверки;
- владение файлами;
- риски безопасности и релиза.

Реализацию не начинать. Вернуть только замечания и итоговую рекомендацию.
EOF

agent-lifecycle adapter task start --adapter codex --file task.md --out intake.json
agent-lifecycle review-mesh recommend --intake intake.json --out review-recommendation.json
```

Если нужно передать переносимый пакет без зависимости от доступа к репозиторию,
соберите несколько Markdown-файлов в один входной файл обычными командами
оболочки:

```bash
mkdir -p work/group-review
{
  printf '# Задача\n\n'
  printf 'Проверь объединённый Markdown-пакет плана. Реализацию не начинать.\n\n'
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

## Средний путь: небольшая группа проверяющих

Создайте профиль для проверки. Он хранит лимиты по токенам/ресурсам и
нейтральные правила независимости. Python-код для этого не нужен:

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

Создайте назначение для каждого проверяющего. Идентификаторы ниже являются
примером, это не имена провайдера или модели:

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

### Конкретные примеры: Codex, Claude и GLM через OpenCode

Конкретная модель выбирается не в переносимом ядре ALK, а в настройках или
флагах конкретного CLI. В ALK-пакетах фиксируйте нейтральный класс модели
через `--reviewer-model-class`, а точную модель проверяйте командой конкретного
CLI.

Сначала можно проверить, что CLI поддерживает явный выбор модели:

```bash
codex exec --help | grep -- "--model"
claude --help | grep -- "--model"
opencode run --help | grep -- "--model"
```

После этого запускайте проверяющих с явным `--model`, чтобы в локальных
подтверждениях было понятно, какая модель использовалась:

```bash
codex exec --model <codex-model-id> \
  "Проверь rm-assignment-a.json и верни только JSON reviewer-output.v1" \
  > reviewer-a-output.json

claude --model <claude-model-alias> --print --output-format json \
  "Проверь rm-assignment-b.json и верни только JSON reviewer-output.v1" \
  > reviewer-b-output.json

opencode models <provider>
opencode run --model <provider>/<model-id> --format json \
  --file rm-assignment-glm.json \
  "Проверь назначение и верни только JSON reviewer-output.v1" \
  > reviewer-glm-output.json
```

Для OpenCode сначала проверьте, что нужная модель видна в списке
`opencode models <provider>`, затем используйте тот же `<provider>/<model-id>` в
`opencode run --model`. GLM-5.2 здесь только пример: если он настроен в вашем
OpenCode, модель может выглядеть как `<provider>/glm-5.2`; для другой модели
укажите её собственный `<provider>/<model-id>`. Если модель настроена как модель
по умолчанию в самом CLI, всё равно лучше указывать `--model` в проверочном
запуске, чтобы в локальных подтверждениях было понятно, какая модель
использовалась.

Если зафиксированный план требует доказать независимость проверяющих, передайте
в ALK не сырое имя модели, а нейтральный хэш:

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

`MODEL_ID='<provider>/glm-5.2'` — пример для GLM. Для другой модели замените
значение переменной, например на модель Codex, Claude, Qwen или локальную модель,
которую поддерживает выбранный CLI.

Передайте каждый пакет назначения выбранному хосту или оператору. ALK не
запускает этих проверяющих. Каждый проверяющий должен вернуть небольшой JSON с
замечаниями и расходом токенов/ресурсов:

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
      "message": "В плане нужен явный шаг отката при неудачном resume."
    }
  ]
}
```

Импортируйте результаты:

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

Импорт маскирует признаки секретов и отклоняет локальные абсолютные пути, если
план явно не разрешил ссылки на локальные подтверждения.

Объедините выводы:

```bash
agent-lifecycle review-mesh synthesize \
  --profile rm-profile.json \
  --result rm-result-a.json \
  --result rm-result-b.json \
  --out rm-synthesis.json
```

Если ведущий уже разобрал замечания, зафиксируйте это явно:

```bash
agent-lifecycle review-mesh synthesize \
  --profile rm-profile.json \
  --result rm-result-a.json \
  --result rm-result-b.json \
  --accepted-finding-id PLAN-1 \
  --out rm-synthesis.json
```

Сформируйте подтверждение кворума:

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

Подтверждение кворума является артефактом проверки. Оно не заменяет проверку
плана, аудит реализации или финальное подтверждение.

## Продвинутый путь: обязательный кворум в плане

Групповая проверка блокирует этапы только тогда, когда зафиксированный план явно
включает это требование. Конфигурация плана может требовать кворум для
выбранных этапов:

```json
{
  "reviewMesh": {
    "required": true,
    "phases": ["freeze", "implementation-audit", "final-audit"],
    "profileDigest": "<profileDigest из rm-profile.json>",
    "quorumReceiptPath": "work/review-mesh/freeze-quorum.json"
  }
}
```

`quorumReceiptPath` используется для проверки при заморозке/принятии плана. Для
аудита реализации и финального аудита передавайте соответствующее подтверждение
явно:

```bash
agent-lifecycle audit implementation \
  --manifest plans/package/plan.manifest.json \
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

## Правила безопасности

- Групповая проверка выключена по умолчанию.
- Рекомендация остаётся советом, пока проверенный план явно не включит режим.
- ALK не вызывает API провайдеров и не запускает CLI проверяющих.
- Переносимые контракты используют нейтральные идентификаторы проверяющих и
  классы моделей, а не конкретные имена провайдера или модели.
- Бюджет задаётся токенами, числом вызовов и временем.
- Импортированный результат не должен содержать секреты или приватные локальные
  пути.

## Короткий чеклист

1. Начните с `adapter task start --file task.md`.
2. Запустите `review-mesh recommend`.
3. Если дополнительная проверка полезна, создайте `rm-profile.json`.
4. Создайте назначение для каждого проверяющего.
5. Запустите проверяющих вне ALK.
6. Импортируйте результаты проверяющих.
7. Объедините выводы.
8. Сформируйте кворум.
9. Подключайте кворум только к тем этапам, где этого требует план.
