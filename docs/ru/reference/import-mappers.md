# Импорт внешних форматов

Импорт внешних форматов переводит сторонние форматы планирования и инструкций в
черновые артефакты ALK. Импортированный контент никогда не считается доверенным
автоматически.

## Поддерживаемые профили форматов

- `openspec-planning`: материалы планирования OpenSpec со спецификациями,
  предложениями, возможностями и изменениями.
- `github-spec-kit-planning`: спецификации, планы и перечни задач GitHub Spec
  Kit.
- `bmad-method-planning`: материалы BMAD: PRD, архитектура, планы и истории.
- `spec-kitty-planning`: материалы Spec Kitty с требованиями, проектированием,
  задачами и проверками.
- `external-workflow-generic`: YAML или JSON, похожий на рабочий процесс, с
  подсказками по шагам, задачам и проверкам.
- `external-agent-generic`: YAML или JSON, похожий на конфигурацию агента или
  запуска, с подсказками по роли, правилам, инструментам и окружению.
- `constitution-adr`: документы в стиле Constitution или ADR с принципами,
  ограничениями, решениями и нумерованными требованиями.
- `agents-agentskills`: файлы `AGENTS.md` или инструкции в стиле agentskills.

Каждый профиль использует `agent-import-dialect-profile.v1` и фиксирует:

- `dialectId` и `dialectKind`;
- `sourceTrusted: false`;
- `requiresReview: true`;
- `freezeBlocked: true`;
- `profileDigest`.

## Поведение импорта

Импорт форматов использует тот же недоверенный путь импорта плана, что и
обычный импорт. Результат `agent-planning-import-result.v1` содержит
`nativeDialectProfileDigest`, а план-кандидат записывает этот же отпечаток в
`candidatePlan.importState.nativeDialectProfileDigest`.

План-кандидат остаётся `DRAFT` с обязательными проверками, аудитом и
заморозкой. Перед реализацией оператор должен пройти обычные этапы проверки и
заморозки ALK.

Общий импорт внешних данных добавляет слой семейства и профиля перед созданием
черновика:

```text
parse -> reject secrets -> normalize/redact hints -> draft -> validate -> review/freeze
```

Импорт семейства workflow переводит шаги, задачи и проверки в черновые
требования, рабочие подсказки и подсказки для проверки. Это контекст для
проверки; ALK не выполняет импортированные узлы workflow.

Импорт семейства agent переводит подсказки по роли и правилам в черновые
требования. Подсказки `provider`, `model`, `auth`, `environment` и `tool`
считаются локальными метаданными хоста. Значения маскируются или представлены
отпечатком и не могут стать переносимыми настройками по умолчанию.

```bash
agent-lifecycle import profile-list
agent-lifecycle import plan --source specs/checkout.md --dialect openspec --out import.json
agent-lifecycle import plan --source specs/ --dialect spec-kit --out import.json
agent-lifecycle import plan --source docs/stories/ --dialect bmad --out import.json
agent-lifecycle import plan --source specs/story.md --dialect spec-kitty --out import.json
agent-lifecycle import external --family workflow --source workflow.yaml --out import.json
agent-lifecycle import external --family agent --source agent.yaml --out import.json
agent-lifecycle import check --candidate import.json
agent-lifecycle import external-check --candidate import.json
```

`import plan --source <folder>` читает только Markdown-файлы, сортирует их по
относительному POSIX-пути и сохраняет обезличенное происхождение в
`agent-markdown-source-collection.v1`. В подтверждении есть имена файлов,
отпечатки и размеры, но нет приватных абсолютных путей.

## Python API

```python
from pathlib import Path

from agent_lifecycle.imports import (
    import_bmad_planning,
    import_external_agent,
    import_external_workflow,
    import_markdown_collection,
    import_agentskills_dialect,
    import_constitution_adr,
    import_openspec_planning,
    import_spec_kit_planning,
    import_spec_kitty_planning,
    validate_import_result,
)

result = import_constitution_adr(Path("architecture-decision.md"))
openspec_result = import_openspec_planning(Path("specs/checkout.md"))
spec_kit_result = import_spec_kit_planning(Path("spec.md"))
bmad_result = import_bmad_planning(Path("story.md"))
spec_kitty_result = import_spec_kitty_planning(Path("design.md"))
folder_result = import_markdown_collection(Path("specs"))
workflow_result = import_external_workflow(Path("workflow.yaml"))
agent_result = import_external_agent(Path("agent.yaml"))
validation = validate_import_result(result)
```

## Правила безопасности

- Внешний входной формат не может обойти проверку ALK.
- Локальные пути и явные признаки секретов блокируют импорт.
- Ограничения ресурсов применяются до генерации плана-кандидата.
- Изменение `profileDigest` приводит к `FAIL`.
- Импорт папки Markdown использует фиксированный порядок файлов и ограничения
  на размер входа.
- Импортированные узлы workflow никогда не выполняются.
- Подсказки `provider`, `model`, `auth`, `environment` и `tool` из входных
  данных семейства agent остаются локальными для хоста и не становятся
  переносимыми настройками ядра.

## Проверяемые границы и ограничения преобразования

Интеграционные регрессии вызывают публичные команды импорта и проверки с
реальными файлами. Парсер, преобразователь и валидаторы не заменяются тестовыми
ответами. Проверяются следующие каналы и запрещённые эффекты:

| Входной канал | Наблюдаемая граница |
| --- | --- |
| Инструкции Markdown, поля структурированного плана и имена источников | Инструкции остаются данными черновика; входные заявления `FROZEN`, доверия и снятия запрета заморозки не заменяют созданные ограничения. |
| Шаги/задачи workflow в JSON и поддерживаемые списки YAML-подобной записи | Команды становятся подсказками для проверки; запуск подпроцесса или сетевое соединение не запрашиваются. |
| Инструкции агента, подсказки provider/model/tool и метаданные окружения | Требования сохраняются для проверки; значения хоста заменяются отпечатками или именами ключей, без переносимых настроек провайдера. |
| Секрет во вложенных метаданных, имени файла, ID профиля или пакета | Импорт завершается отказом до записи результата; диагностика CLI не содержит секрет. |
| Созданное подтверждение с изменёнными полями полномочий и пересчитанным отпечатком | Публичная команда проверки отклоняет повышение доверия, разрешение выполнения, настройки провайдера и снятие проверок, аудита или запрета заморозки. Совпадение отпечатка не даёт полномочий. |

Тесты эффектов наблюдают `subprocess.Popen`, `os.system` и вызовы соединения
сокетов, а также сравнивают все файлы временной рабочей папки, включая контрольные
файлы полномочий и профиля модели. Успешный импорт добавляет только запрошенное
подтверждение черновика; проверка не меняет рабочую папку. Отдельные утверждения
проверяют сохранение полезного требования к status endpoint, имён источников,
размеров в байтах, отпечатков и привязок профиля. Это ограниченные локальные
регрессии, а не доказательство защиты от произвольной prompt injection в модель,
всех инструментов хоста или любых побочных эффектов. Вредоносный текст может
сохраниться как материал для проверки. Последующий хост должен считать его данными.

Семантические примеры для синонимов workflow (`steps`/`jobs`,
`validation`/`validations`/`checks`) и преобразования роли/правил агента находятся в
[`test_external_dialects.py`](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/imports/test_external_dialects.py).
Преобразователь принимает объекты JSON и ограниченную YAML-подобную запись, а не
произвольный движок workflow на YAML. Он сохраняет максимум восемь требований,
обрезая каждое до 180 символов; рабочие и проверочные подсказки workflow также
ограничены восемью. Отпечаток исходника сохраняет идентичность, а не полноту
семантического перевода. Перед одобрением объёма работ проверяющий должен свериться
с исходником. Проверки доверия, обязательного ревью, запрета заморозки и изменения
отпечатка профиля находятся в
[`test_external_dialect_framework.py`](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/imports/test_external_dialect_framework.py);
проверки эффектов CLI и подмены подтверждений — в
[`test_untrusted_input_boundaries.py`](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/imports/test_untrusted_input_boundaries.py).

Матрица CI также требует Node smoke для фактической
[`проекции OpenCode`](https://github.com/avksp/agent-lifecycle-kit/blob/main/adapters/opencode/plugins/agent-lifecycle-kit.js).
Тест разбирает и импортирует её байты как ES-модуль, проверяет экспортированную
функцию и неизменяемые метаданные, затем вызывает функцию и проверяет пустой
объект хуков. Единственный подпроцесс использует существующий ограниченный
транспорт с лимитом 15 секунд, 4096 байт stdout и 8192 байт stderr. Если Node
недоступен, CI завершается ошибкой; локальный пропуск означает отсутствие этого
доказательства. Проверяются только синтаксис и экспорт: тест не запускает OpenCode,
Bun или модель, не квалифицирует установленный маршрут хоста и не меняет текущую
квалификацию OpenCode 1.x/2.x или ограничения неподдерживаемых операций.
