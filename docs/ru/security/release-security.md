# Безопасность релиза

## Текущая карта контроля

Карта описывает проверки текущего исходного дерева. Проверка исходников,
необязательный отчёт анализа и квалифицированная операция хоста — разные
свидетельства. Ни одно из них отдельно не доказывает готовность релиза или
отсутствие уязвимостей.

### Проверки во время выполнения

| Контроль | Владелец | Проверка | Ограничение |
| --- | --- | --- | --- |
| Отказ при распознанных секретах до создания кандидата импорта или вывода, включая вложенный текст, метки, family и метаданные профиля (`import-sensitive-content`). | [planning.py](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/imports/planning.py), [external_dialects.py](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/imports/external_dialects.py), [общая редакция](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/contracts/redaction.py) | [границы вывода CLI](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/cli/test_import_security_boundaries.py), [импорт планов](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/imports/test_planning_imports.py) | Общие категории секретов и чувствительные ключи, а не обнаружение любого секрета или внедрения инструкций. Безопасный импорт остаётся черновиком без полномочий выполнения. |
| Ограничение чтения файлов находок и коллекций Markdown; отказ при ссылках и смене идентичности. До сортировки собирается не более `maxFiles + 1` подходящих записей; превышение отклоняется без чтения содержимого файлов. | [security_findings.py](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/imports/security_findings.py), [multi_markdown.py](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/imports/multi_markdown.py), [authority_io.py](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/contracts/authority_io.py) | [импорт находок](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/imports/test_security_findings.py), [коллекции](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/imports/test_multi_markdown_imports.py) | Чтение ограничено лимитом байтов плюс один байт обнаружения; коллекция использует общий лимит. Сохранён `security-analysis-import-too-large`. Все записи обхода имеют отдельные лимиты ниже. |
| Ограничение всего поиска Markdown, включая пустые деревья и файлы других типов; отказ при недоступных метаданных, ссылках, reparse points и смене идентичности каталогов до чтения содержимого и создания кандидата импорта. | [multi_markdown.py](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/imports/multi_markdown.py), [authority_io.py](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/contracts/authority_io.py) | [границы коллекции, вложенные потребители и отказы CLI](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/imports/test_multi_markdown_imports.py) | Метаданные проверяются не более чем у `4096` записей; ещё одна запись определяет превышение без проверки метаданных. Не более `256` каталогов с учётом корня; глубина `32`, корень `0`; кооперативный монотонный срок `5` секунд с проверками вокруг операций поиска. Превышение вызывает `markdown-collection-discovery-limit-exceeded`. Виртуальные часы проверяют кооперативный контроль; системный вызов нельзя прервать. Жёсткий таймаут системного вызова и гарантия для всех хостов не заявляются. |
| Связывание замороженного пакета с lock до выполнения и аудита. | [freeze](https://github.com/avksp/agent-lifecycle-kit/tree/main/src/agent_lifecycle/freeze), [workflow](https://github.com/avksp/agent-lifecycle-kit/tree/main/src/agent_lifecycle/workflow) | [тесты freeze](https://github.com/avksp/agent-lifecycle-kit/tree/main/tests/freeze) | Целостность и проверка полномочий не доказывают смысловую правильность плана или реализации. |

### CI и проверки исходников

| Контроль | Владелец | Проверка | Ограничение |
| --- | --- | --- | --- |
| Статическая политика запуска учитывает алиасы импортов, from-import, лексические области и методы; проверяет shell и ограниченные маршруты процессов. | [валидатор запуска](https://github.com/avksp/agent-lifecycle-kit/blob/main/tools/release/validate_adapter_launcher_security.py) | [мутации запуска](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/release/test_adapter_launcher_security.py), [алиасы и области](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/release/test_adapter_launcher_security_validator.py) | Только распознаваемые формы AST; не доказательство для произвольного динамического Python или всех инструментов хоста. Идентичность и редакция во время выполнения остаются отдельными проверками. |
| Проверка неизменяемых ссылок Actions, явных разрешений и обнаружения тестов. | [валидатор CI](https://github.com/avksp/agent-lifecycle-kit/blob/main/tools/release/validate_ci_security.py), [workflow CI](https://github.com/avksp/agent-lifecycle-kit/blob/main/.github/workflows/ci.yml) | [тесты безопасности CI](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/release/test_ci_security_validator.py) | Конфигурация репозитория не подтверждает действующую защиту ветки, одобрение или успех публикации. |
| Отказ при отслеживаемых маркерах секретов, локальных путях и неподтверждённых заявлениях адаптеров. | [тесты безопасности релиза](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/security/test_release_security.py) | Набор безопасности запускается прямо в [CI](https://github.com/avksp/agent-lifecycle-kit/blob/main/.github/workflows/ci.yml). | Конечный набор маркеров и заявленные свидетельства; не универсальный сканер секретов и не квалификация хоста. |
| Проверка происхождения тега и идентичности публикации; PyPI Trusted Publisher через окружение `pypi`. | [workflow публикации](https://github.com/avksp/agent-lifecycle-kit/blob/main/.github/workflows/publish.yml), [валидатор release-ref](https://github.com/avksp/agent-lifecycle-kit/blob/main/tools/release/validate_release_ref.py) | [тесты release-ref](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/release/test_release_ref_validator.py) | Реальное одобрение окружения, опубликованные артефакты и provenance требуют текущих внешних свидетельств. Автономная генерация исходного релиза остаётся локальной и не требует учётных данных или сети. |

### Необязательный анализ безопасности

[Профиль анализа безопасности](../reference/security-analysis-profile.md)
имеет статус `OPTIONAL`, выключен по умолчанию и отделён от проверок выше.
Его [владелец](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/quality/security_analysis.py) и
[тесты приёмки](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/workflow/test_security_analysis_profile.py)
покрывают явное включение, ограниченное разрешение и независимую проверку
доработок высокой серьёзности, на которые распространяется политика.
Импорт находки не запускает сканер или эксплуатацию и не устанавливает
статус уязвимости или промышленной готовности.

### Ограничения хостов

Текущая поддержка Codex ограничена обычными операциями. Защищённое закрытие
и маршруты оператора остаются неподдерживаемыми; `ORDINARY_LIMITED` не является
защищённым запасным маршрутом. Граница описана в
[контракте оператора](../reference/host-local-token-accounting.md) и
[тестах отказа](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/cli/test_closing_window_commands.py).
Статус адаптера `GUIDANCE_ONLY` означает рекомендации, а не принуждение;
см. [свидетельства действий](../reference/adapter-action-evidence.md) и
[владельца квалификации](https://github.com/avksp/agent-lifecycle-kit/blob/main/src/agent_lifecycle/host_protocol/lifecycle_control_qualification.py).
Эти проверки не доказывают устойчивость к внедрению инструкций на каждом хосте.

Файлы окружения локального хоста в live-обвязках требуют явного
`--host-env-allow` и свидетельства
[гигиены окружения](https://github.com/avksp/agent-lifecycle-kit/blob/main/tools/release/validate_host_env_hygiene.py);
[тесты валидатора](https://github.com/avksp/agent-lifecycle-kit/blob/main/tests/release/test_host_env_hygiene_validator.py)
покрывают этот ограниченный маршрут. Закрытые ключи, токены, cookie и пути
локальной машины не должны попадать в переносимые артефакты релиза.
Безопасность и учёт ресурсов — отдельные контрольные точки: PASS одной
не заменяет другую.

## Исторические контракты релиза 1.75

Обзор 1.75 описывал подписанные подтверждения нейтральности, связывающие
утверждения с операцией и основным артефактом, проверку ревизий Git,
редакцию, лимиты JSON, права закрытых файлов, строгий разбор Ed25519,
связь плана с lock и неизменяемые ссылки CI. Сохранены ссылки на
[контракт нейтральности](neutrality-contract.md),
[публичные локаторы и редакцию](../reference/public-locators-and-redaction.md)
и [историческую архитектуру релиза (англ.)](https://github.com/avksp/agent-lifecycle-kit/blob/main/docs/architecture/release-architecture.md).
Исторические свидетельства публикации 1.74/1.75 не доказывают происхождение
текущего дистрибутива. Промышленное продвижение требует внешних органов
подписи и проверки и текущих свидетельств; эти полномочия не хранятся
в репозитории.

Одиночные planning/external imports используют стабильное чтение без следования ссылкам, максимум cap плюс один байт для обнаружения превышения. Значения Cookie/Set-Cookie и fine-grained токены GitHub чувствительны. Лексическая нормализация сохраняет обычные пути с .. для этих одиночных API и external CLI. Требуются переносимые сегменты пути: symlinks, reparse points, необычные файлы и непереносимые имена явно отклоняются. CLI коллекций Markdown сохраняет отдельную политику путей. При превышении inputBytes означает прочитанные detection bytes, а не полный размер файла.
