# Предметный язык проекта

Предметный язык проекта — необязательный локальный словарь терминов, которые
должны оставаться согласованными в спецификации, API, коде, тестах и
документации. Он полезен, когда одно слово используется в нескольких
ограниченных контекстах, например в трёх контекстах `qualification`,
зафиксированных для ALK. Это не универсальная политика именования и не
требование перечислять каждый идентификатор.

## Полномочия и границы

Артефакт использует контракт `agent-project-domain-language.v1`. У каждого
термина есть стабильный `termId`, английская и русская формы и определения,
необязательные синонимы, контексты и нормализованные ссылки на файлы проекта.
Артефакт хранится под контролем версий, имеет ревизию и собственный digest.

Спецификация и зафиксированный план остаются источниками полномочий. Словарь
не может менять требование, принимать результат или понижать гейты
безопасности, качества и риска. Он не выдаёт полномочия записи. ALK не
переименовывает файлы и текст автоматически. Если словаря нет, возможность не
активируется и обычная работа не получает дополнительного сканирования или
runtime-расхода.

Ссылки задаются относительно репозитория. Абсолютные пути, `..`, значения,
похожие на URI, симлинки, исполняемые инструкции, секреты и данные конкретного
провайдера отклоняются. Аудит работает только для чтения и ограничен по
ресурсам: он не изменяет код, планы, документацию или состояние workflow.

## Форма артефакта

Создайте локальный файл, например `docs/domain-language.json`:

```json
{
  "schemaVersion": "agent-project-domain-language.v1",
  "languageId": "checkout-terms",
  "revision": 1,
  "defaultLocale": "en",
  "terms": [
    {
      "termId": "qualification",
      "labels": {"en": "Qualification", "ru": "Квалификация"},
      "definitions": {
        "en": "A bounded validation of a named capability.",
        "ru": "Ограниченная проверка названной возможности."
      },
      "aliases": [
        {"value": "qualification receipt", "locale": "en", "status": "ACTIVE"}
      ],
      "contexts": ["agent-plugin", "benchmark", "structured-result"],
      "references": [
        {"kind": "documentation", "path": "docs/terms.md", "locator": "qualification"}
      ]
    }
  ],
  "authority": {
    "role": "terminology-reference",
    "sourceOfTruth": "specification-and-frozen-plan",
    "semanticReview": "independent-review"
  },
  "source": {"kind": "project-local", "path": "docs/domain-language.json"},
  "productionPromotionClaimed": false,
  "languageDigest": "<sha256-объекта-без-languageDigest>"
}
```

Артефакт проверяется контрактом `agent-project-domain-language-validation.v1`.
Используйте статус `ACTIVE` для текущих синонимов и `DEPRECATED`, когда после
проверенного переименования нужно показать оставшиеся ссылки. Устаревший
синоним создаёт находку, но не запускает автоматическую правку.

## Команды

Проверьте артефакт без запуска модели или внешнего CLI:

```bash
agent-lifecycle project language check \
  --file docs/domain-language.json \
  --project-root .
```

Посмотрите выбранные термины и затронутые файлы без изменений:

```bash
agent-lifecycle project language audit \
  --file docs/domain-language.json \
  --project-root . \
  --term-id qualification \
  --changed-path docs/terms.md \
  --out work/domain-language-audit.json
```

Аудит возвращает `PASS`, `DRIFT`, если объявленный устаревший синоним всё ещё
встречается в ссылках, или `FAIL` для повреждённых, отсутствующих, выходящих за
границы и недоступных входов. Конверт имеет схему
`agent-project-domain-language-audit.v1`, а `readOnly` всегда равен `true`.

Свяжите две проверенные ревизии словаря с дельтой плана:

```bash
agent-lifecycle plan delta \
  --before path/to/plan-v1/plan.manifest.json \
  --after path/to/plan-v2/plan.manifest.json \
  --language-before path/to/domain-language-v1.json \
  --language-after path/to/domain-language-v2.json \
  --out work/plan-delta.json

agent-lifecycle plan delta-check --delta work/plan-delta.json
```

Раздел `agent-project-domain-language-delta.v1` показывает добавленные и
удалённые термины, изменения меток, устаревшие синонимы и детерминированный
набор затронутых ссылок. Он связан digest-ами, работает только для чтения и
требует новой ревизии словаря. Он не заменяет решение о новом ревью или lock в
дельте плана.

## Как внедрять

Начните с небольшого набора терминов, из-за которых уже возникает дрейф
документации или повторное ревью. Дайте каждому термину стабильный ID и
связывайте только те файлы, которые проверяющий должен обновить. Разделяйте
три контекста ALK `qualification`, если у них разные требования или
подтверждения приёмки. Изменения словаря рассматривайте как вход в план, а не
как доказательство корректности реализации.

См. [принципы проекта и дельты плана](project-principles-and-plan-deltas.md),
а также [публичные контракты](public-contracts.md) со списком схем.
