# Адаптер Hermes

Проекция Hermes содержит общие навыки жизненного цикла, `skills.sh.json`,
метаданные реестра и команд со слешем под `adapters/hermes/`, а также манифест
возможностей.

Текущий уровень поддержки: `VERIFIED` для Hermes Agent `v0.19.0`. Он включает
проверенный диапазон хоста и подтверждения из резюме проверки.

Установка отдельного навыка из отмеченного тега:

```bash
hermes skills install https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/vX.Y.Z/skills/agent-workflow-orchestrator/SKILL.md
```

Проверка:

```bash
agent-lifecycle adapter validate \
  --descriptor adapters/hermes/adapter.descriptor.json \
  --baseline conformance/core/adapter-baseline.v1.json

agent-lifecycle adapter inspect \
  --descriptor adapters/hermes/adapter.descriptor.json \
  --skip-host-commands
```

Резюме локального осмотра: `docs/adapters/evidence/hermes-0.8.0.md`.
Принятое резюме реального запуска: `docs/adapters/evidence/hermes-host-local-live-2026-07-29.md`.
Проверенный локальный профиль задаёт маршрут запуска CLI хоста.

## Запуск только для планирования

Точная версия профиля: `0.19.0`. Состояние профиля: `UNSUPPORTED`.
Поддержка запуска планирования: `PLANNING_ONLY_UNSUPPORTED`. Порядок
квалификации включает однократный запуск со встроенным запретом опасных
инструментов и соответствующее подтверждение.

Создание и проверка локального профиля:

```bash
agent-lifecycle adapter launch-profile --adapter hermes --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/hermes.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/hermes.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/hermes.json
```

Маршрут планирования использует статус и подтверждения из раздела [запуск адаптера только для
планирования](../reference/planning-only-launch.md).

## Статус контроля жизненного цикла

Для адаптера Hermes каждая операция дескриптора (`install`, `discover`, `validate-envelope`, `launch`, `model-route-execution`, `wait`, `cancel`, `resume`, `tool-execution`, `adapter-event-stream`, `result-collection`, `usage-attestation`, `task-audit`, `final-audit`) публикует
`declaredLevel: GUIDANCE_ONLY`, `supportedLevel: GUIDANCE_ONLY`,
`qualifiedLevel: GUIDANCE_ONLY` и `qualificationStatus: NO_RECOMMENDATION`.
Статус управляемого запуска - `WRAPPER_ONLY`. Это значения контроля жизненного
цикла для отдельных операций, а не общий уровень поддержки адаптера в матрице.

Страница и навык адаптера объясняют порядок работы ALK внутри хоста. Они не
заявляют, что промпт, плагин или обёртка блокируют действие. Позже для отдельных
операций можно квалифицировать производителя хоста для точной версии, но
одних офлайн-фикстур для повышения уровня недостаточно. См. [необязательный
контроль жизненного цикла](lifecycle-control.md) и [использование ALK с
адаптером](usage-modes.md).

## Использование ALK в Hermes

После установки навыка из отмеченной версии выполните внутри Hermes:

```text
/agent-lifecycle-kit:agent-workflow-orchestrator Проведи полный цикл ALK: проверенное планирование, фиксацию плана, аудит результатов реализации и принятое итоговое доказательство. Задача: <задача или Markdown-файл>
```

Для запуска вне Hermes:

```bash
agent-lifecycle start --adapter hermes --file task.md
```

Первый способ управляется внешним инструментом, а второй создаёт входные
артефакты ALK в терминале. Полный цикл подтверждают переходы состояния,
проверки, аудиты и принятые артефакты. Подробнее: [использование ALK с
адаптером](usage-modes.md).
