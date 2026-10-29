# Модульная архитектура controller

Документ определяет production shape controller Agent Lifecycle Kit. Архитектура host-neutral и применима ко всем адаптерам `adapters/*`, включая Codex, Claude Code, Cursor, Gemini CLI, Goose, Grok Build, Hermes, Kimi Code, OpenCode, OpenInterpreter, Pi и Qwen Code.

## Статус

Исторический монолит `workflowctl.py` не входит в standalone production source. Он остаётся только characterization и bootstrap reference в source projects, которые ещё его содержат.

Standalone release реализует controller как модульный Python package с тонкими entrypoints и domain packages. Большинство основных seams уже имеют production modules. Reserved seams следует превращать в packages только при появлении behavior или когда split предотвращает превышение file/context limit.

## Текущая карта реализации

| Ответственность | Текущие модули | Статус |
| --- | --- | --- |
| Стабильные contracts, canonical JSON, digests, schemas и typed errors | `contracts/*` | Реализовано |
| Обнаружение Git diff для ownership audit | `changesets/git.py` | Реализовано |
| Аудит ownership, implementation, package, proof integrity и review verdict | `audit/*` | Реализовано |
| Проверка SDD tier и plan manifest | `planning/*`, `specification/*`, `review/*` | Validators реализованы |
| Проверка plan lock | `freeze/locks.py` | Реализовано |
| Компиляция frozen DAG в task packets и small-model packets | `compiler/task_packets.py`, `compiler/small_model_packets.py` | Реализовано |
| Compact context profiles, rendering, episode retrieval и external context | `context/*`, `context/external_memory.py`, `evidence_index/external_context.py` | Реализовано |
| Durable workflow state, operation kernel, event log, task/run transitions, gate checks, finalization | `workflow/*` | Реализовано |
| Neutrality authority, scanning, signed receipts и controller-gate helper | `neutrality/*` | Реализовано |
| Host capability descriptors, inspection, event capture и validation | `host_protocol/*`, adapter metadata files | Реализовано как offline descriptors и validation contracts |
| Adapter task intake, sessions, launch profiles и workflow bridge | `adapter_sessions/*` | Реализовано |
| Импорт external workflow, dialect и planning | `imports/*`, including OpenSpec, Spec Kit, BMAD and Spec Kitty profiles | Реализовано как draft-only import mappers |
| Readiness diagnostics и diagnostic bundles | `diagnostics/*` | Реализовано |
| Evidence indexes, episode indexes и external-context receipts | `evidence_index/core.py`, `evidence_index/episode_index.py`, `evidence_index/external_context.py` | Реализовано |
| Goal records, objective snapshots, read-only goal view и follow-up records | `goal/records.py`, `goal/view.py`, `followup/*` | Реализовано |
| Usage, phase resources, cost accounting и outcome signals | `metrics/*` | Реализовано |
| Provider-neutral model class routing и receipts | `model_routing/*` | Реализовано |
| Adaptive lifecycle policy, quality-floor decisions и provider-neutral execution strategy | `policy/*`, including `policy/execution_strategy.py`, plus `cli/strategy.py` | Реализовано |
| Deterministic reference-task evaluation и quality-first strategy comparison | `benchmarks/*`, `contracts/benchmark_schemas.py`, `cli/benchmarks.py` | Реализовано |
| Optional quality profiles, cross-check, bug forensics и advisory | `quality/*`, `quality/bug_forensics_advisor.py` | Реализовано |
| Read-only status, progress, event feed и change summaries | `reporting/*` | Реализовано |
| Optional multi-review coordination, templates, packets, assignments, import, synthesis и quorum | `review_mesh/*`, `review_mesh/operator_templates.py` | Реализовано |
| Controlled runner, attempt snapshots и sandbox receipts | `runner/*` | Реализовано |
| Worktree isolation receipts | `worktree/*` | Реализовано |
| Корневая CLI dispatch | `cli/main.py`, `cli/parsers.py`, `cli/dispatch.py`, `cli/dispatch_adapters.py`, `cli/dispatch_contracts.py`, `cli/dispatch_lifecycle.py`, `cli/dispatch_observability.py`, `cli/dispatch_planning.py` | Тонкий entrypoint и обработчики групп команд реализованы; lifecycle semantics переносить сюда нельзя |
| Release checks и live adapter promotion evidence | `tools/release/*`, `tools/live_hosts/*`, metadata and docs | Реализовано как release validators и host-local evidence tooling |

Текущая проверка размеров: `cli/main.py` и `cli/dispatch.py` содержат соответственно 41 и 53 строки и остаются тонкими entrypoints. Root dispatcher выбирает focused adapter/readiness, contract/evidence, lifecycle, observability или planning handler; policy, follow-up и worktree handlers остаются отдельными command modules. Большинство production Python files ниже hard limits документа. `workflow/plan_adoption.py`, `workflow/finalization.py` и `workflow/task_transitions.py` сохраняют примерно 420–440 строк. Для нового lifecycle behavior следует выбирать focused domain module и небольшой dispatcher submodule, а не расширять `cli/dispatch.py`.

## Целевая структура

Каждая граница становится package только при существующем runtime behavior или для предотвращения превышения file/context limit:

- `contracts`: public schemas, canonical JSON, digests и typed errors.
- `ports`: host, filesystem, Git, signing, clock, process и telemetry ports; сейчас преимущественно lightweight direct stdlib calls.
- `state`: state/WAL schemas, readers, projections и compatibility; сейчас `workflow/state.py` и `workflow/events.py`.
- `operation_kernel`: atomic state/event/WAL transactions и crash recovery; сейчас `workflow/operation_kernel.py` с expected revision checks, operation-id idempotency, state revision mutation, operation ledger, event append и atomic state replacement.
- `planning`: SDD tier resolution, specification, review и freeze logic.
- `context`: compact profile validation, active-packet rendering, overflow checks и context receipts для small-context hosts.
- `compilation`: компиляция и проверка frozen DAG/task packets; сейчас `compiler/task_packets.py`.
- `authorization`: approval receipts, bootstrap preflight и auto-authorize; сейчас ограничено run authorization fields в `workflow/plan_adoption.py`.
- `task_runtime`: launch, status, attempt, remediation и acceptance; сейчас `workflow/task_transitions.py` и selectors.
- `runner`: bounded execution loop над существующими workflow primitives; contracts и extension points описаны в [договоре переходов](runner-transition-contract.md) и [карте расширений](runner-extension-map.md).
- `validation`: controller gates, command receipts, release validators и indexes; сейчас `workflow/gates.py`, `neutrality/gate.py`, `tools/release/*`.
- `audit`: ownership, task/package implementation audits, proof integrity, review verdicts и final audit validators; сейчас `audit/*`, `workflow/reviews.py`, `workflow/finalization.py`.
- `quality`: bug-forensics, cross-check, failure classification и optional quality packs.
- `review_mesh`: optional multi-review recommendation, assignments, imported results, synthesis и quorum validation.
- `adapter_sessions`: descriptor-driven task intake, session records, secure launch profiles и managed workflow bridge.
- `reporting`: read-only status, event feed, lifecycle progress, progress hooks и change summaries.
- `metrics`: token/resource accounting, usage export, outcome indexes и quality-cost recommendations.
- `model_routing`: provider-neutral model class decisions и receipts.
- `execution_strategy`: provider-neutral сочетание risk, quality floor, model class, packet size, review depth и resource limits; сейчас `policy/execution_strategy.py` с CLI и compiler projections.
- `benchmarks`: deterministic reference-task evaluation и quality-first comparison receipts; сейчас `benchmarks/*`, `cli/benchmarks.py`.
- `worktree`: isolation policies и attempt receipts.
- `release`: release candidate, inventory и support matrix; сейчас docs, metadata и release validators.
- `terminal`: только terminal progress rendering; direct terminal host operations вне core.
- `finalization`: final proof, terminal proof и COMPLETE replay checks; сейчас final proof/final audit validation в `workflow/finalization.py`.
- `adapters`: только host-specific projections без lifecycle semantics.
- `api`: stable public API поверх modular services; сейчас package facades и root CLI.
- `cli`: только argument parsing и compact rendering.

Зависимости односторонние: lower layers не могут импортировать CLI, API или surface adapters; adapters не могут напрямую импортировать controller domain services. Controller services зависят от ports и contracts, а не native host APIs.

## Проверяемые архитектурные границы

Reviewed package levels записаны в `policy/architecture-dependencies.json`. Release validator строит module graph исходников, учитывает imports внутри functions, отвергает non-trivial module/package cycles и проверяет направление каждого edge. CI выполняет эту проверку вместе с source-size и function-complexity validator: архитектура — исполняемое release condition. Текущий graph acyclic; новая dependency требует обновления policy и независимого review.

Runtime boundaries подчиняются тому же правилу. `adapter_sessions/process.py` — bounded process boundary; `process_capture.py` отвечает за stream capture, `process_control.py` — за timeout, cleanup и receipt assembly. Public launcher и start modules сохраняют совместимые facades при разделённой реализации. Persistence helpers в `contracts/persistence.py` объединяют private create, replace и permission rules в одной реализации.

Host inspection принимает adapter-owned data, но не произвольный код. Адаптер может предоставить literal-only `inspection_profile.py`. ALK проверяет profile, выбирает только allow-listed inspection handler и сообщает unsupported profile без запуска host process. Загрузка использует bounded literal parsing и никогда не импортирует adapter code. Поэтому новый inspection profile не требует новой host-name branch в lifecycle core.

## Ограничения размера и контекста

Standalone implementation должна работать с small-context models. File/function limits — release gates.

`policy/architecture-limits.json` — единственная authority для validator и CI. Targets обозначают advisory split candidates; hard limits блокируют.

| Policy key | Limit |
| --- | ---: |
| `targetFileLines` | 800 |
| `hardFileLines` | 1200 |
| `targetFunctionLines` | 80 |
| `hardFunctionLines` | 150 |
| `hardSymbols` | 80 |
| `cliTargetFunctionLines` | 80 |
| `cliHardFunctionLines` | 150 |

Branch/private-import ratchets и compatibility boundaries описаны в [системной архитектуре](system-architecture.md#стабилизация-архитектуры-и-совместимость). Existing debt виден; PASS hard gate не означает достижения каждого target. Отдельные external-launcher limits остаются target 12 / hard 24 строки; top-level-symbol context target — 40, enforced hard limit — 80.

Точная context authority — rendered C8 subject, а не line-count heuristic. Каждый changed production slice должен иметь bounded subject, помещающийся в C8 profile. Overflow необходимо устранить split subject или module до review.

`small-context-profile.v1` — portable compact-context baseline для 4k-strict, 8k, 16k, 32k и 64k hosts без silent truncation. CLI также возвращает non-zero при провале budget checks rendered context receipt. Host может использовать больший local context, но adapter не может заявлять compact-mode support без неизменного PASS core-rendered envelope и receipt.

Receipt должен применять все bundled profile budgets в runtime: rendered envelope, reserved-output budget, active packet, state summary, accepted evidence summary, optional `toolOutputs` и recent verbatim user-turn count. При любом провале controller блокирует или делит input, а не создаёт усечённый prompt.

Controller gates — runtime preconditions. Task/finalization transitions проверяют каждый gate текущей фазы по frozen receipt path: binding, freshness, dependencies, PASS verdict и required attestation fields до изменения state.

## SOLID

SOLID обязателен там, где создаёт проверяемые границы:

- Single responsibility: один lifecycle concern на module.
- Open/closed: новые host adapters добавляются через ports и adapter packages, без lifecycle core branches.
- Liskov/interface segregation: explicit capability contracts и fail-closed для unsupported operations.
- Dependency inversion: lifecycle logic зависит от ports, а не concrete host runtimes или shell wrappers.

SOLID не оправдывает deep inheritance, abstract factories или framework-heavy structure. Предпочтительны small pure functions, dataclasses, protocols и explicit composition.

## DRY

DRY обязателен для lifecycle semantics и security-sensitive logic:

- одна canonical JSON implementation;
- один digest/signature path на domain;
- один operation kernel для state/WAL commits;
- один evidence/receipt validation path;
- одна adapter capability model.

DRY не должен объединять различные trust domains в generic helper. Similar code может оставаться раздельным, когда bootstrap, release, terminal, task и validation требуют разных signatures, schemas или failure semantics.

## YAGNI

YAGNI обязателен для adapter/plugin scope:

- поставлять только семь canonical lifecycle skills;
- держать optional live adapter promotion вне release prerequisite;
- не добавлять MCP servers, apps, hooks или marketplaces без требования target host;
- не реализовывать provider-specific model routing в core;
- не поставлять project profiles или source-project samples в этом repository.

YAGNI не отменяет required safety. Durable state, WAL, immutable locks, independent review, evidence binding, authority checks, bounded context, crash recovery и final proof остаются core requirements.

## Условие приёмки

Release candidate не проходит, если:

- production source импортирует, исполняет или возвращает исторический монолит `workflowctl.py`;
- lifecycle semantics отдельно реализованы в host adapters;
- module превышает hard size/context limits без approved split;
- security-sensitive canonicalization, signing, receipt или WAL logic имеет несколько authoritative implementation paths;
- adapter support заявлен выше conformance evidence в support matrix;
- samples, fixtures или evaluations содержат source-project names, paths, credentials или artifacts.
