# Быстрый старт

Этот пример показывает минимальный полезный запуск из исходного дерева. Он не
делает реальных вызовов модели и не меняет настройки локальной среды.

## Установка из исходников

```bash
python -m pip install -e .
agent-lifecycle version
```

Без установки можно запустить команду прямо из дерева:

```bash
PYTHONPATH=src python -m agent_lifecycle version
```

## Установка из пакета

Если пакет опубликован для нужного релиза, устанавливайте точную
семантическую версию:

```bash
python -m pip install agent-lifecycle-kit==1.44.0
agent-lifecycle version
```

Если пакет ещё не опубликован, используйте установку из исходного дерева выше.
Одного Git-тега недостаточно для установки плагина: манифесты плагина внутри
тега тоже должны содержать ту же версию. Подробнее:
[публикация плагинов](reference/plugin-publication.md).

## Проверка готовности

```bash
agent-lifecycle diagnose --no-install-plans
```

Отчёт не раскрывает локальные абсолютные пути и секреты. Команда проверяет
метаданные пакета, профили, дескрипторы адаптеров, безопасный осмотр и
публичные резюме подтверждений. Реальные вызовы моделей не запускаются.

Для одного адаптера:

```bash
agent-lifecycle diagnose \
  --adapter adapters/codex/adapter.descriptor.json \
  --no-install-plans
```

## Пробный план установки адаптера

```bash
agent-lifecycle adapter install-plan \
  --descriptor adapters/opencode/adapter.descriptor.json
```

Команда показывает, какие файлы, команды и действия оператора понадобятся. Она
не меняет настройки локальной среды и не повышает зрелость адаптера.

## Проверка плана

Для зафиксированного плана:

```bash
agent-lifecycle plan check \
  --manifest path/to/plan.manifest.json \
  --lock path/to/plan.lock.json
```

План остаётся источником правды для владельца, границ записи, критериев
приёмки, проверок и подтверждающих артефактов.

## Импорт файлов планирования

Чтобы проверить внешний файл планирования перед превращением в план ALK:

```bash
agent-lifecycle import plan \
  --source specs/checkout.md \
  --dialect openspec \
  --out work/imports/checkout-import.json
```

Чтобы проверить папку с несколькими Markdown-файлами:

```bash
agent-lifecycle import plan \
  --source specs/checkout/ \
  --dialect spec-kit \
  --out work/imports/checkout-folder-import.json
```

Эта же команда поддерживает `--dialect bmad` и `--dialect spec-kitty`.
Импортированный материал остаётся черновым кандидатом. Он не запускает
реализацию и не заменяет зафиксированный план ALK, пока не пройдёт проверку и
заморозку.

## Приём задачи для адаптера

Для файла задачи или короткого текста:

```bash
agent-lifecycle adapter task start --adapter codex --file task.md
agent-lifecycle adapter task start --adapter codex --text "Исправь падающий тест"
```

Обычный текст не запускает реализацию. Команда возвращает черновое
подтверждение, которое должно пройти проверку. Управляемое выполнение требует
зафиксированного запроса запуска или зафиксированного плана с привязкой к
рабочему циклу.

## Проверка изменений

Для локальной ветки, запроса на слияние в GitHub или запроса на слияние в
GitLab сначала подготовьте файл изменений и короткую задачу проверки:

```bash
mkdir -p work/code-review/current
git diff origin/main...HEAD > work/code-review/current/diff.patch
```

Затем передайте задачу в ALK без запуска реализации:

```bash
agent-lifecycle adapter task start \
  --adapter codex \
  --file work/code-review/current/review-task.md \
  --out work/code-review/current/intake.json

agent-lifecycle review-mesh recommend \
  --intake work/code-review/current/intake.json \
  --out work/code-review/current/recommendation.json
```

Используйте этот путь для обычной проверки файла изменений, архитектурной проверки,
проверки безопасности и оценки риска перед слиянием. Подробные примеры для
GitHub, GitLab, архитектуры и аудита реализации:
[сценарии проверки кода](code-review-workflows.md).

## Дополнительная перепроверка

Для исследования, планирования или сложного аудита можно сначала получить
локальную рекомендацию групповой проверки:

```bash
agent-lifecycle review-mesh recommend --file task.md
```

Если проверенный зафиксированный план явно включает этот режим, используйте
`review-mesh assign`, `import-result`, `synthesize` и `quorum`, чтобы
координировать подтверждения проверяющих без запуска хостов из ядра ALK.
Подробные примеры:
[практические сценарии групповой проверки](review-mesh-workflow.md).

## Компактный контекст

Перед передачей задачи небольшой модели проверьте профиль:

```bash
agent-lifecycle context check \
  --profile profiles/small-context-profile.v1.json
```

Профиль удерживает контекст коротким и явным, но не отключает обязательные
проверки качества.

## Что дальше

- [Установка адаптеров](adapters/install.md)
- [Сценарии проверки кода](code-review-workflows.md)
- [Справочник команд](reference/cli.md)
- [Диагностика готовности](reference/readiness-diagnostics.md)
