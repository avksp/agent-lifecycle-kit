# Интеграция внешнего клиента AI SDLC

Внешний клиент может вызывать установленный `agent-lifecycle` CLI как ограниченный
subprocess и показывать receipts. Задачник, IDE, скрипт и другой клиент используют
один контракт; отдельный сервис задачника и private Python imports не требуются.
ALK владеет workflow authority. Клиент отвечает за запуск процесса, отображение
и сверку результата. Host отвечает за выполнение модели и подлинную usage
attestation; независимый reviewer — за выводы review.

Руководство задаёт provider-neutral контракт CLI-потребителя для release 2.35.0.
Оно не добавляет server, daemon, provider broker, runtime API или вторую state
machine. Описанная поверхность намеренно ограничена. Остальные операции сохраняют
свои [CLI-контракты](../reference/cli.md).

## Согласовать совместимость до mutation

Клиент MUST выполнить `agent-lifecycle version` и потребовать
`agent-lifecycle-version.v1`. Он MUST сравнить `version` с явно протестированной
таблицей версий. Контракт 2.35.0 не квалифицирует более ранний или поздний release
только по сходству номера. Клиент MUST отказать в mutation при неизвестной версии,
неизвестной `schemaVersion`, неподдерживаемом action или несовместимом обязательном
поле. Read-only диагностика может оставаться доступной с явной пометкой об
отсутствии квалификации. Нельзя угадывать flags, молча удалять guards или понижать
версию schema.

Используйте `agent-lifecycle schema list --scope core` и
`agent-lifecycle schema show <schema-id>` для доступных описательных контрактов;
аргументы проверяйте через `--help` установленной команды. Registry не является
универсальным wire protocol или сервисом авторизации. Runtime validators также
проверяют межфайловые bindings. Клиент хранит свою таблицу проверенных версий,
операций, receipt/action schemas, обязательных полей и исходов отказа.

Передавайте массив аргументов с отключённым shell evaluation. Задавайте явный
рабочий каталог repository, пределы input/output и timeout; сохраняйте stdout,
stderr, exit code, timestamps и точную identity executable. При timeout, отказе
процесса, повреждённом/усечённом output или неизвестном receipt фиксируйте неизвестный
результат и сверяйте факт до следующей mutation. Ошибки аргументов CLI могут выводить
parser diagnostics в stderr вместо JSON. Обработанная lifecycle error использует
`agent-lifecycle-error.v1` и exit 2. Exit 0 сам по себе не доказывает успех:
`workflow continue` может вернуть `INPUT_REQUIRED`, `WAITING` или `BLOCKED` с exit 0.

## Привязать запрос к native authority

Клиент MUST сохранять repository, package ID, plan revision и полный plan digest,
identities проверенного manifest и lock, run ID/state path, текущую state revision,
source revision, task ID и attempt, когда применимо. Все result, review, audit,
usage и proof artifacts связываются с той же lineage. Пути continuation inputs —
repository-relative. Полные digests являются identities; сокращённое отображение
не заменяет входное значение.

Frozen manifest и `agent-plan-lock.v2` связывают проверенный план. Freeze не
авторизует исполнение. Native state и transitions определяют authorization,
готовность зависимостей, ownership, attempts, независимую acceptance и completion.
Текущие native state formats включают `agent-workflow-state.v4` и
`agent-workflow-state.v5`; поддержка задаётся явной таблицей клиента и не разрешает
автоматически переписывать или мигрировать state. Legacy migration использует
отдельную guarded command. Статус UI — проекция этих фактов, а не authority.

## Ограниченная карта операций

Каждая строка называет существующую команду, её schema/guard и boundary.
Необязательные output-файлы receipts являются evidence writes, а не workflow
authority writes.

| Actor и операция | Существующая команда и schema/guard | Отказ и boundary |
| --- | --- | --- |
| Клиент: определить установку | `agent-lifecycle version`; `agent-lifecycle-version.v1`, `version` | Неизвестная version/schema запрещает mutation клиента; state transition отсутствует. |
| Клиент: проверить входы плана | `agent-lifecycle plan verify --manifest <manifest> --package-root <plan-root> --acceptance <checklist> --repository-root . --out <receipt>`; `agent-plan-verification-receipt.v1` | Проверить `status`, именованные checks и blockers. Отсутствующий/изменённый lock, некорректная traceability или ownership запрещают готовность. Структурная проверка не является semantic review, authorization или acceptance. |
| Клиент: спроецировать следующий action | `agent-lifecycle workflow continue` с bindings ниже; `agent-workflow-continuation-receipt.v1`, вложенный `agent-workflow-continuation-action.v1` | Без `--apply` нет authority mutation. `requiredInputs`, blockers и допустимость route остаются определяющими; projection не запускает host или модель. |
| Авторизованный controller: применить один поддерживаемый action | Тот же запрос `workflow continue` плюс `--apply --projected-state-revision <n> --projected-action-digest <full-digest>`; те же receipt/action schemas и существующие transition validators | Требуются текущая revision, точный action digest, source/plan/lock lineage и подлинные route-specific inputs. Отсутствующие inputs, устаревшая lineage, отсутствие authorization, некорректная ownership или независимое review запрещают transition. Только `APPLIED` с совпадающими committed state/event устанавливает факт применения. |
| Controller/host: выбрать model class | `agent-lifecycle model route --profile <routing-profile> --host-profile <host-profile> --request <request>`; вход `agent-lifecycle-model-route-request.v1`, выход `agent-lifecycle-model-route-decision.v1` | Детерминированные policy/capability/context/critical-review checks; неподходящий critical route получает отказ. Decision не запускает модель и не разрешает workflow transition. |
| Host/controller: проверить usage | `agent-lifecycle model usage-check --receipt <usage> --route-decision <decision> --budget-targets <targets>`; вход `agent-lifecycle-model-usage-receipt.v1` | Проверяются host attestation, route binding и budgets; некорректная/unattested usage возвращает `model-usage-validation-failed`. Одна validation не принимает task. |

Некоторые flags model route и usage необязательны; этот контракт потребителя
передаёт явные profiles, decision и budget targets, чтобы их identities можно было
проверить. Существующие role classes, quality floors, critical-review rules и
host-local mapping моделей описаны в [Model routing](../reference/model-routing.md).
Portable plans не выбирают конкретные provider models. Это руководство не
заменяет routing policy и не квалифицирует новый host.

## Projection, входы, затем apply

Это шаблон команды, а не разрешение изменять настоящий run:

```bash
agent-lifecycle workflow continue \
  --state work/run.state.json \
  --manifest work/plans/release-x/plan.manifest.json \
  --lock work/plans/release-x/plan.lock.json \
  --operation-id client-start-WS-01-attempt-1 \
  --expected-revision 7 \
  --source-revision <source-sha> \
  --reason "project a bounded task start" \
  --task WS-01
```

Для квалифицированного receipt клиент MUST проверить `mode: PROJECT`,
`stateWritten: false`, `modelCallsStarted: false` и `hostLaunchStarted: false`,
затем изучить `status`, `plan`, `stateBefore`, `action`, `requiredInputs` и
`blockers`. `READY` означает возможность передать этот action его guards. Это
не означает, что task начат или завершён. Если есть `nextAction.argv`, это tokens
аргументов с `shell: false`; до вызова проверьте executable, bindings и допустимый
route. Нельзя исполнять содержимое receipt как shell string.

Передайте входы, запрошенные фактическим route, и повторите projection, если входы
изменились. Сохраните operation identity. Для apply используйте тот же запрос
и inputs с `--apply`, вернувшимся `action.stateRevision` как
`--projected-state-revision` и полным `action.actionDigest` как
`--projected-action-digest`. `--expected-revision` должен оставаться текущим.
ALK пересчитывает action и вызывает существующий transition; cached projection
не обходит guards. Применённый one-step receipt использует `mode: APPLY`,
`status: APPLIED`, `stateWritten: true`, `stateAfter` и `appliedEvent` для committed
revision.

| Projected route | Inputs и native boundary |
| --- | --- |
| Authorization / run start | `--authorization-receipt`, когда требуется; проверенный план, совпадающий lock и отдельная execution authorization. Draft или `PLAN_ONLY` недостаточны. |
| Task start | Допустимый `--task`; `--risk-profile` или strategy inputs, когда выбранный route их требует. Native dependency, ownership, attempt и budget guards сохраняются. Запись task start не запускает host. |
| Task result | `--result`, а также `--model-usage-receipt` и `--budget-targets`, когда требуются. Текущие source/change-set claims и подлинная bound usage проверяются до review. |
| Task review outcome | `--review`, `--implementation-audit`, когда требуется, и `--finding-id` для применимой remediation. Независимый reviewer предоставляет вывод; controller применяет его. |
| Final audit outcome / finalization | `--final-audit` и соответствующие outcome `--verdict`, `--task-id`, `--finding-id`; finalization дополнительно потребляет обязательные proof, integrity и completion-gate inputs. Следуйте projected `requiredInputs` и существующим finalization gates. |

Полная существующая карта flags и bounded bundle mode приведены в
[Workflow continuation](../reference/workflow-continuation.md). Клиент MUST
останавливаться на host, model, reviewer, operator, plan-authority и resource
boundaries. Он MUST NOT создавать синтетические review/usage attestations,
редактировать state/lock вручную или превращать локальный boolean `done` в native
acceptance. Task acceptance, final independent audit, native finalization и
последующая publication остаются отдельными gates.

## Сверить неизвестный результат

До dispatch сохраняйте один operation ID с точным запросом, projected state
revision/action digest и identities inputs. Native operation ledger ALK отклоняет
уже использованный operation ID; это не сервис cached responses. Retry с новым
ID не является безопасным способом узнать, произошла ли предыдущая mutation.

После потери ответа клиент MUST остановить mutation и прочитать canonical state,
объявленный в нём event journal и сохранённый native receipt, если он есть.
Сверьте run/package, operation ID, committed revision, event type/task/attempt и
artifact bindings. Workflow events используют `agent-workflow-event.v1`. Если
совпадающие event и state устанавливают нужный transition, запишите наблюдаемый
факт и спроецируйте следующий action без повтора transition. Одна более поздняя
revision не доказывает успех.

Если достоверно установлено, что operation не committed, а state/journal
согласованы, получите свежую projection и соблюдайте существующие guards
неиспользованной operation до retry. Если evidence отсутствует, противоречит
друг другу или указывает на partial persistence, сохраните UNKNOWN и остановитесь
для существующего recovery/operator route. Нельзя исправлять историю записью
успешного event или повтором host-команды. Native operation guards не гарантируют
exactly-once исполнение произвольных host/model/external side effects; для них
нужны собственные host-owned evidence сверки.

## Сохранять подлинные usage и evidence

Сохраняйте exact source, digests executable/configuration/inputs, command/exit/time,
identities receipts и изменённых файлов. Настоящая model usage передаётся через
существующий host-attested receipt и квалифицированный normalizer; оценка UI,
fixture или serialization helper не создают attestation. Model-backed task results
отказывают при отсутствующей, unattested или lineage-drifted usage. Недоступные
tokens, provider cost и полный host input остаются `UNKNOWN`/null, а не измеренным
нулём. Считайте shell/process, validation, model invocations и physical CI отдельно;
сохраняйте прежние расходы, failed attempts и исходные часы через retries.

Conformance на disposable fixture имеет статус `UNIT_ONLY`. Детерминированный
consumer test может наблюдать ноль model calls; он не доказывает live review,
host enforcement или production qualification. См.
[Host-local token accounting](../reference/host-local-token-accounting.md) и
[Safe artifact authoring](../reference/safe-artifact-authoring.md). Корректный
JSON artifact не делает его утверждения истинными и не завершает bound run.
