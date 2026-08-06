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

## Приём задачи для адаптера

Для файла задачи или короткого текста:

```bash
agent-lifecycle adapter task start --adapter codex --file task.md
agent-lifecycle adapter task start --adapter codex --text "Исправь падающий тест"
```

Обычный текст не запускает реализацию. Команда возвращает черновой receipt,
который должен пройти проверку. Управляемое выполнение требует
зафиксированного run request или зафиксированного плана с привязкой к рабочему
циклу.

## Дополнительная перепроверка

Для исследования, планирования или сложного аудита можно сначала получить
локальную рекомендацию Review Mesh:

```bash
agent-lifecycle review-mesh recommend --file task.md
```

Если проверенный зафиксированный план явно включает этот режим, используйте
`review-mesh assign`, `import-result`, `synthesize` и `quorum`, чтобы
координировать подтверждения проверяющих без запуска хостов из ядра ALK.
Подробные примеры: [практические сценарии Review Mesh](review-mesh-workflow.md).

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
- [Справочник команд](reference/cli.md)
- [Диагностика готовности](reference/readiness-diagnostics.md)
