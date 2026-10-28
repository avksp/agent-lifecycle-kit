# Хранение состояния workflow и восстановление

Инициализация нового workflow остаётся `agent-workflow-state.v4`. Кандидат
runtime 2.30 поддерживает inline v4 и явный компактный `agent-workflow-state.v5`.
Миграция меняет представление данных, сохраняя полномочия выполнения. Все
последующие чтения authority и изменения требуют квалифицированного runtime
с поддержкой v5; native loaders 2.27 и 2.29 отказывают по версии схемы.
Автоматического downgrade нет.

## Представление и пределы

Компактный state сохраняет текущие задачи, ограниченную историю попыток,
бюджеты, авторизацию и append-only operation ledger. Неизменяемые ownership
receipts, result change-set evidence и полные снимки прошлых планов хранятся как
canonical JSON в соседнем каталоге `.storage/objects/`. Одинаковые тела используют
один объект. Ссылка `agent-workflow-storage-reference.v1` содержит kind, SHA-256,
bytes, path, lineage и item counts. SHA-256 считается по canonical JSON без LF;
bytes включает один конечный LF. Исторические evidence сохраняют исходные
plan/task/attempt lineage. Снимки сохраняют роль
`HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING`.

| Ограничение | Предел |
| --- | --- |
| Каждый authority JSON, включая root и каждый leaf | 1 048 576 байт |
| Текущие задачи / снимки прошлых планов / записи operation ledger | 32 / 128 / 2 048 |
| Различимые достижимые объекты / полный достижимый объём | 4 096 / 64 MiB |
| Суммарные различные объекты/байты одной операции валидации | 4 096 / 64 MiB |
| Весь сохранённый storage, включая orphan после retry | 128 MiB |
| Глубина ссылок | State → snapshot → leaf, максимум два ребра |
| Кооперативный deadline storage I/O | 30 секунд на одну операцию |

Эти счётчики не гарантируют размещение любой комбинации больших metadata.
Остаточные inline metadata также должны укладываться в root limit. Один слишком
большой leaf вызывает отказ: произвольные объекты не разбиваются на части.
Предупреждения начинаются на 75% лимита root/счётчиков/объёма. Capacity refusal
сообщает category, current, required, limit и маршрут migration/replanning.
История, расходы, operation IDs и UNKNOWN holds не удаляются ради места.
Недостижимые immutable объекты сохраняются; команды сборки мусора нет.

Каждое чтение authority и изменение проверяет весь достижимый граф, включая
старые снимки, которые не выбраны текущей задачей. Отсутствующие, повреждённые,
неканонические данные и неверные kind, hash, длина, lineage или counts вызывают
отказ. Циклы, вложенные snapshots, path aliases, traversal, symlinks и Windows
reparse paths не поддерживаются. Ограниченный контекст операции переиспользует
проверенные raw bytes и исходный deadline; доверие не переносится на следующую
операцию. Deadline проверяется вокруг I/O и не прерывает зависший syscall ОС.

## Явная миграция

До миграции сохраните полный state, event log, связанные артефакты и source
identities. Передайте точные текущие state/source revisions и уникальный
operation ID, например:

```sh
agent-lifecycle workflow state-migrate \
  --state work/run/state.json \
  --target-schema agent-workflow-state.v5 \
  --expected-revision 64 --source-revision <source-sha> \
  --operation-id migrate-storage-64
```

Миграция допустима для BLOCKED с истёкшей авторизацией. Она создаёт и проверяет
неизменяемый соседний `state.json.v4-backup-<raw-sha>.json`, подготавливает sidecars
и записывает одну реальную revision/operation/event и migration receipt. Receipt
связывает исходные raw bytes/hash, source/target revisions и storage root.
Event log остаётся append-only. Phase, blockers, grants и expiry/revocation,
run/attempt clocks, неудачные попытки, бюджеты, расходы, UNKNOWN и identities
принятых артефактов сохраняются. Миграция не возобновляет и не принимает задачу.
Повторная миграция не создаёт ещё одно event или charge.

Если state расположен вне уже игнорируемого рабочего каталога, до native
snapshots настройте обычные Git exclusions для всего authority footprint.
Для `state.json` и `events.jsonl` в корне соответствующие записи такие:

```gitignore
/state.json
/state.json.storage/
/state.json.v4-backup-*.json
/events.jsonl
```

При необходимости исключите и объявленный каталог runtime artifacts проекта.
Используйте фактические имена и каталоги state/events: игнорирование только
root state не исключает sidecars и backups. Это обычная настройка Git. Она не
ослабляет ownership для посторонних исходников и не создаёт host enforcement.

## Отказы и восстановление

Чистая подготовка и preflight будущих root/event/checkpoint/sidecar происходят
до публикации. Существующий private contained no-replace authority I/O сохраняет
объекты до публикации ссылок. Проверенный same-byte orphan можно переиспользовать
при retry; другие байты по существующему digest path вызывают отказ. Observer
и policy получают точные подготовленные записи sidecar и backup.

Отказ до публикации сохраняет state/events без изменений. Поздний отказ может
оставить immutable объекты или checkpoint, event без нового state либо уже
сохранённый state. Сохраните фактический partial outcome и receipt. Расхождение
event/state требует существующего split-brain recovery; одна ошибка ответа не
доказывает rollback или task acceptance. Writers сериализуются существующей
transaction lock и stale revision guards; более широкой гарантии параллельных
writers нет.

Сохраните квалифицированный v5 runtime и разберите конкретный missing/corrupt
object или capacity gate. Не исправляйте ссылки, подписанные артефакты, grants,
ledger или clocks вручную. Восстановление pre-migration snapshot допустимо только
в одноразовой изолированной реплике после сохранения failed/post-migration
evidence. Immutable v4 backup служит доказательством, не разрешением отката live
run. Live in-place rollback и downgrade не поддерживаются.

## Отдельное продление авторизации

`workflow authorization-renew --receipt <fresh-receipt>` — отдельный явный
same-run переход с обычными state/source/revision/operation guards. Typed
`agent-workflow-authorization-renewal-receipt.v1` связывает предыдущий grant,
текущую lineage, неизменные бюджеты, исходные clocks и task/artifact identities.
Меняется только authorization expiry. Digest фиксирует declared user authority
в существующей границе доверия, а не новую подпись.

Допустимы RUNNING с существующей VERIFYING задачей и committed result либо
FINAL_AUDIT со всеми required tasks в ACCEPTED. BLOCKED/technical recovery,
closingWindow, revoked/ungranted, plan-only, terminal и unsupported legacy grants
вызывают отказ. Продление не возобновляет, не запускает, не повторяет и не
принимает работу, не расширяет бюджет и не продлевает run/attempt deadlines.
Обычная acceptance продолжает проверять evidence; после неё активные attempt
clocks могут канонически удаляться, а исторические evidence сохраняют исходные
значения. Существующие unsupported-host и DECLARED-ledger ограничения остаются.

Акторы portable fixture явно синтетические. Component scale, native fixture,
изолированная application rehearsal и live acceptance имеют разный охват.
Изолированная RMK rehearsal мигрирует точный исторический incident64 и проверяет
только expired-authorization refusal. Она не продлевает live grant, не принимает
GUARDS и не закрывает RMK incident. Live recovery требует актуальных project-owned
review, path/source reconciliation и явной авторизации после qualified delivery.
