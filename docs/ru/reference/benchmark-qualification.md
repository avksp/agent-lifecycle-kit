# Проверка вариантов выполнения по эталонным задачам

[Английская версия](https://github.com/avksp/agent-lifecycle-kit/blob/main/docs/reference/benchmark-qualification.md)

Эта проверка отвечает на узкий вопрос: можно ли сравнить два внешних запуска ALK
по качеству и подтверждённым ресурсам. Вариант выполнения — это нейтральное
сочетание адаптера, класса модели, среды и оценщика. Внешний адаптер, модель или
рабочая оболочка выполняет запуск. ALK читает полученные записи выполнения,
проверяет их происхождение и создаёт ограниченный отчёт без запуска процесса.
В имени схемы техническое слово `receipt` сохранено ради совместимости.

## Раздельные измерения

Каждый запуск хранит отдельно:

- эталонную задачу, семейство, уровень и явную форму задачи;
- нейтральный класс адаптера и вариант выполнения;
- отпечаток среды;
- отпечаток оценщика;
- отпечаток исходной записи выполнения.

Имена провайдеров и моделей, команды, учётные данные и абсолютные локальные
пути не входят в переносимую запись выполнения. Класс варианта, например `standard` или
`local-code`, является нейтральной классификацией, а не именем провайдера.

## Воспроизводимая выборка

```bash
agent-lifecycle benchmark sample \
  --suite benchmarks/reference-tasks/manifest.json \
  --seed project-baseline \
  --max-tasks 24 \
  --max-strata 16 \
  --out work/benchmark/sample.json
```

Для одинаковых набора, начального значения и ограничений выборка совпадает.
Группы строятся по полям манифеста `family`, `tier` и `shape`; результат
содержит выбранные и пропущенные идентификаторы задач. Во встроенном наборе
заданы пять форм: `planning`, `review`, `investigation`, `implementation` и
`evidence`.

## Проверка внешней записи выполнения

Внешний исполнитель создаёт файл `agent-benchmark-run-receipt.v1`. Объекты
варианта выполнения, среды, оценщика и источника содержат нейтральные данные с
отпечатками. ALK проверяет запись без вызова указанного исполнителя:

```bash
agent-lifecycle benchmark receipt-check \
  --suite benchmarks/reference-tasks/manifest.json \
  --receipt work/benchmark/run-01.json \
  --out work/benchmark/run-01-validation.json
```

Результат проверки имеет схему `agent-benchmark-run-receipt-validation.v1`.
Устаревший отпечаток задачи, отсутствие отпечатка измерения, смешанные
переносимые данные или изменённый отпечаток записи выполнения приводят к отказу.

## Проверка варианта выполнения

Передайте по одной записи на каждый параметр `--receipt`. Для сравнения разных
вариантов выполнения используйте одну и ту же выборку:

```bash
agent-lifecycle benchmark qualify \
  --suite benchmarks/reference-tasks/manifest.json \
  --sample work/benchmark/sample.json \
  --receipt work/benchmark/baseline-01.json \
  --receipt work/benchmark/baseline-02.json \
  --out work/benchmark/baseline-qualification.json
```

Вариант получает технический статус `QUALIFIED` только при наличии:

- не менее пяти разных задач;
- не менее двух завершённых запусков каждой задачи;
- не менее пяти разных групп `family/tier/shape`;
- не менее двух завершённых запусков каждой группы;
- общего и пройденного числа критериев для каждого запуска;
- явного результата проверки ложной приёмки и отсутствия пробела в данных о качестве.

Иначе отчёт получает `NO_RECOMMENDATION`. Качество и ложная приёмка
проверяются до сравнения токенов, времени, повторов и ресурсов.

## Сравнение двух вариантов выполнения

```bash
agent-lifecycle benchmark compare-routes \
  --suite benchmarks/reference-tasks/manifest.json \
  --sample work/benchmark/sample.json \
  --baseline work/benchmark/baseline-01.json \
  --baseline work/benchmark/baseline-02.json \
  --candidate work/benchmark/candidate-01.json \
  --candidate work/benchmark/candidate-02.json \
  --out work/benchmark/route-comparison.json
```

Отчёт отдельно показывает изменения варианта, среды и оценщика. Разные наборы
задач, среды, оценщики или уровни подтверждения использования дают
`INCOMPARABLE` или `NO_RECOMMENDATION`, а не вводящий в заблуждение выбор
победителя. Отчёт носит рекомендательный характер и не переключает адаптер,
модель или зафиксированный план.

## Облачные, малые и локальные модели

Одинаковый процесс принимает записи выполнения от облачной, малой контекстной или
локальной модели. Адаптер на стороне хоста передаёт нейтральный класс варианта,
отпечаток среды и уровень подтверждения использования. ALK не додумывает
отсутствующие данные о токенах, не складывает оценочные и подтверждённые
значения и не считает отсутствие измерения отсутствием расхода. Отчёт
эталонных задач не является заявлением о промышленной готовности.

## Ранжирование квалифицированных данных

```bash
agent-lifecycle benchmark rank-qualified --request local-ranking.json --out new-report.json
```

Чистый API:
`agent_lifecycle.model_routing.qualified_selection.rank_qualified_routes(request, *, now=None)`.
Подстановка `now` предназначена только для библиотечных тестов; CLI использует
текущее UTC. Ручной запрос содержит
`schemaVersion=agent-qualified-route-ranking-request.v1` и необязательное
`enabled=false`. При включении дополнительно обязательны все поля:

- `modelRequest` и `routingProfile` по существующим контрактам model routing;
- `hostIdentityDigest`, `productSourceDigest`, `environmentDigest`, `scorerDigest`;
- `metric`: `tokens` или `elapsedMilliseconds`; целое `maxAgeSeconds`: 1..604800;
- `trustedReceiptDigests`: не более 192 различных SHA256 в нижнем регистре;
- `candidates`: не более трёх объектов ровно с полями `id`, `hostProfile`,
  `modelClass`, `hostBindingDigest`, `receipts` (не более 64 на кандидата).

ID кандидата — переносимый непрозрачный идентификатор длиной 1..64 символа.
ID и digest binding различаются; профили указывают один хост. Выбранные resolver
класс и binding должны совпадать с кандидатом. Digest записываются hex в нижнем
регистре. Лимиты входа: 1 MiB, глубина 16, 12000 узлов значений JSON. Неизвестные
ключи, дубликаты JSON-ключей, неверные числовые типы, nonfinite и ссылки запрещены.
Отчёт ограничен 64 KiB; пути из содержимого evidence не открываются.

`trustedReceiptDigests` — список полных записей, ранее независимо принятых
вызывающей стороной вне consumer. Совпадение хеша доказывает целостность
относительно списка, но не подлинность, финансовую аттестацию, поддержку хоста или
полноту сбора. ALK не обнаруживает пропущенные вызовы и не доказывает, что
производитель наблюдал каждый вклад. Реестр подписей или доверия не добавляется.

Каждая запись проходит существующий validator и свежую квалификацию с прежними
минимумами: пять разных задач, два завершённых прогона на задачу, пять страт и
два прогона на страту. Все критерии качества выполнены, false acceptance=false,
measurement gaps пусты, usage confidence=`ATTESTED`. ID и полные digest записей
глобально уникальны; повторные записи не заполняют минимумы.

`measurements.acceptedTaskTotal` каждой записи содержит ровно `scope`,
`accepted`, `complete`, `observedAt`, `hostIdentityDigest`,
`productSourceDigest`, `contributions`. Scope=`ACCEPTED_TASK_TOTAL`; оба флага
равны true. `observedAt` — UTC RFC3339, не из будущего; возраст не превышает
`maxAgeSeconds`, включая точную границу. Digest хоста и исходников совпадают с
запросом, как и digest окружения и scorer в записи.

Каждый вклад содержит ровно `id`, `role`, `tokens`, `elapsedMilliseconds`,
`evidenceDigest`. ID уникальны внутри задачи. Обязательны все шесть ролей:
coordinator, worker, review, audit, retry, correction. Нулевой вклад задан явно и
связан с provenance. Пропущенная роль, неизвестный итог или отсутствующий
64-hex evidence digest не превращаются в ноль. Счётчики — целые 0..2**53-1;
boolean запрещён. Обе суммы вкладов равны внешним итогам записи. Tokens включают
input/output и вложенные cache/reasoning ровно один раз; доли не пересекаются.
Elapsed — интервалы принятой задачи, без суммирования параллельного wall time
reviewer. Нормализация производителя остаётся внешней обязанностью.

Все кандидаты имеют одинаковые мультимножества task ID/version/digest,
family/tier/shape и числа прогонов. Исходники продукта, хост, окружение и scorer
совпадают; digest отдельных execution source могут различаться. Существующие
попарные сравнения маршрутов должны пройти с аттестованным usage до ранжирования
ресурсов. Любой пробел отклоняет весь список. Рейтинг сортируется по целой сумме
выбранной метрики, при равенстве — по порядку входа; экстраполяции нет.

Схема отчёта — `agent-qualified-route-ranking.v1`. Поля: status, ограниченные
reason codes, ID выбранного кандидата или null, ranking, metric, digest запроса,
квалификаций, сравнений и отчёта. При отказе ranking пуст. Частные имена моделей
скрыты. Всегда сохраняются `advisoryOnly=true`,
`automaticRouteAdoptionEligible=false`, `productionPromotionClaimed=false`,
`modelCallsStarted=false`, `hostLaunchStarted=false`, `profileMutation=false`,
`liveEconomicQualification=UNQUALIFIED`, `savingsClaimed=false`. Положительные
fixtures — `UNIT_ONLY`; экономическая квалификация живого хоста отложена.
