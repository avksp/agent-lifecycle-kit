# Быстрый Старт

Этот пример показывает самый короткий полезный запуск из исходного дерева. Он
не делает живых вызовов модели и не записывает настройки среды.

## Установка Из Исходников

```bash
python -m pip install -e .
agent-lifecycle version
```

Без установки можно запустить из дерева:

```bash
PYTHONPATH=src python -m agent_lifecycle version
```

## Проверка Готовности

```bash
agent-lifecycle diagnose --no-install-plans
```

Отчет редактированный: без локальных абсолютных путей и без секретов. Проверка
смотрит метаданные пакета, профили, дескрипторы адаптеров, безопасный осмотр,
публичные резюме доказательств и объявленные локальные сырьевые квитанции. Живые
вызовы не запускаются.

Для одного адаптера:

```bash
agent-lifecycle diagnose \
  --adapter adapters/codex/adapter.descriptor.json \
  --no-install-plans
```

## Сухой План Установки Адаптера

```bash
agent-lifecycle adapter install-plan \
  --descriptor adapters/opencode/adapter.descriptor.json
```

Команда показывает файлы, команды и действия оператора. Она не меняет настройки
среды и не повышает зрелость адаптера.

## Проверка Плана

Для замороженного плана:

```bash
agent-lifecycle plan check \
  --manifest path/to/plan.manifest.json \
  --lock path/to/plan.lock.json
```

План остается источником правды для владельца, границ записи, приемки, проверок
и доказательств.

## Компактный Контекст

Перед передачей задачи небольшой модели проверьте профиль:

```bash
agent-lifecycle context check \
  --profile profiles/small-context-profile.v1.json
```

Профиль держит контекст коротким и явным, но не отключает ворота качества.
