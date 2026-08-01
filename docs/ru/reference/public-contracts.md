# Публичные контракты

Публичные контракты — это стабильные схемы JSON, которыми связаны CLI,
документация, тесты и проверочные артефакты.

## Основные контракты

- `completionCheck`: обязательный task-level gate завершения.
- `agent-completion-check-receipt.v1`: подтверждение завершения.
- `agent-goal-record.v1`: запись цели.
- `agent-objective-snapshot.v1`: компактный снимок цели.
- `agent-runner-state.v1`: состояние управляемого выполнения.
- `agent-runner-snapshot.v1`: компактный снимок runner state.
- `agent-follow-up-register.v1`: реестр продолжений.
- `agent-follow-up-summary.v1`: краткое состояние продолжений.
- `agent-worktree-isolation-policy.v1`: политика изоляции рабочего дерева.
- `agent-worktree-attempt-receipt.v1`: подтверждение изоляции рабочего дерева.
- `agent-worktree-writeback-receipt.v1`: решение apply/discard для overlay.
- `agent-adapter-event-stream-receipt.v1`: поток событий адаптера.
- `agent-adapter-event-capture-validation.v1`: проверка capture evidence.
- `agent-review-verdict.v1`: проверочный вердикт.
- `agent-review-routing-summary.v1`: routing summary для review.
- `agent-optional-quality-pack.v1`: opt-in пакет качества.
- `agent-behavior-check-run.v1`: результат behavior-check.
- `agent-task-template-library.v1`: каталог draft-only task templates.
- `agent-task-template-library-validation.v1`: проверка task templates.
- `agent-task-template-render.v1`: render result одного task template.
- `agent-bug-forensics-recipe-library.v1`: каталог Bug Forensics recipes.
- `agent-bug-forensics-recipe-validation.v1`: проверка Bug Forensics recipes.
- `agent-diagnostic-bundle.v1`: диагностический пакет.
- `agent-readonly-status-view.v1`: read-only status view.
- `agent-workflow-event-feed.v1`: read-only event feed по workflow state.
- `agent-lifecycle-progress-view.v1`: read-only lifecycle progress view.
- `agent-proof-finding.v1`: стабильная идентичность finding.
- `agent-root-cause-evidence.v1`: подтверждение root cause.
- `agent-fix-impact-receipt.v1`: канонический receipt влияния исправления.
- `agent-receipt-hash-chain.v1`: append-only цепочка receipts.
- `agent-proof-integrity-receipt.v1`: общий receipt целостности
  подтверждений.
- `agent-sandbox-receipt.v1`: runtime evidence для filesystem, network,
  process, environment и enforcement source.
- `agent-sandbox-requirement.v1`: fail-closed политика обязательного sandbox
  evidence для high-risk задач.
- `agent-sandbox-capability.v1`: декларация sandbox capabilities адаптера.
- `agent-adapter-probe-profile.v1`: профиль capability bench.
- `agent-adapter-probe-plan.v1`: declarative adapter probe plan.
- `agent-adapter-probe-evidence-validation.v1`: проверка probe evidence/drift.
- `agent-adapter-package-discovery.v1`: advisory source-tree discovery.
- `agent-import-dialect-profile.v1`: профиль внешнего dialect import.
- `agent-episode-index.v1`: rebuildable индекс receipt/session episodes.
- `agent-episode-retrieval.v1`: bounded retrieval result с digest provenance.
- `agent-runner-attempt-snapshot-receipt.v1`: receipt snapshot/restore/abandon
  и selected-attempt metadata.
- `agent-worker-lease-receipt.v1`: receipt lease/heartbeat state worker-а.
- `agent-phase-resource-measurement.v1`: phase-level tokens/resources через
  usage export envelope без обязательного USD-cost.
- `agent-cross-check-profile.v1`: optional cross-check profile, выключенный по
  умолчанию и capped в tokens/resources.
- `agent-cross-check-receipt.v1`: receipt дополнительной проверки.
- `agent-runtime-policy-receipt.v1`: receipt runtime policy decision.
- `agent-bug-forensics-profile.v1`: optional профиль для bug/regression repair.
- `agent-bug-reproduction-receipt.v1`: reproduction-before-modification
  evidence.
- `agent-failure-fingerprint.v1`: стабильный fingerprint ошибки.
- `agent-bug-hypothesis-ledger.v1`: accepted/rejected hypotheses и
  minimal-patch gate.
- `agent-regression-proof-receipt.v1`: тот же fingerprint red before / green
  after.
- `agent-bug-forensics-gate-receipt.v1`: workflow gate receipt.
- `agent-bug-forensics-audit.v1`: audit summary для bug-forensics gate.
- `agent-lifecycle-policy-proposal.v1`: предложение по настройке правил.

## Правило совместимости

Новые схемы должны добавляться явно и проходить `agent-lifecycle contract
check`. Изменение контракта без тестов и документации считается небезопасным.

`agent-fix-impact-receipt.v1` — основной контракт для фиксации влияния
исправления. Он связывает changed files, finding ids, digest root cause,
изменённые и сохранённые behavior contracts, regression evidence и проверку
побочного влияния.

`agent-sandbox-receipt.v1` не заменяет
`agent-worktree-attempt-receipt.v1`. Worktree receipt ограничивает пути записи
в репозитории, а sandbox receipt описывает runtime containment. `UNKNOWN` —
валидное явное состояние capability, но required high-risk policy принимает
только настроенные passing statuses, по умолчанию `PASS`.
Partial containment и credential proxy boundaries остаются details внутри
`agent-sandbox-receipt.v1`; отдельный execution-sandbox schema alias не
вводится.

Adapter probe plan является release-time drift detector для live conformance.
Он не запускает live calls, не меняет maturity и не заявляет production
promotion.

`agent-import-dialect-profile.v1` требует `sourceTrusted: false`,
`requiresReview: true` и `freezeBlocked: true`. `nativeDialectProfileDigest`
фиксирует provenance импортированного dialect, но не означает approval.

Generic external workflow и agent/harness imports используют тот же
`agent-import-dialect-profile.v1` с family/profile metadata. Workflow-family
imports создают reviewable requirements и validation hints без выполнения
imported nodes. Agent-family imports держат provider, model, auth, environment и
tool hints как redacted host-local metadata; это не portable defaults.

`agent-episode-retrieval.v1` возвращает bounded context projection по явно
переданным receipt/session artifacts. Result получает `chainVerified` только
при совпадении path и digest с hash-chain entry; иначе state остаётся
`chainUnchecked`.

Runner recovery receipts добавляют evidence для нескольких попыток, но не
заменяют workflow state. Cross-check profile остаётся advisory и opt-in, пока
план явно не требует blocking cross-check. Independence проверяется по
нейтральным `hostIdentityHash` и `modelIdentityHash`, а не по именам
провайдеров.

`agent-runtime-policy-receipt.v1` отделяет доказанное pre-execution enforcement
от advisory-only logging. `agent-worktree-writeback-receipt.v1` фиксирует
apply/discard overlay и не заменяет `agent-sandbox-receipt.v1`.

Bug Forensics включается только явным task/profile marker. Для impact он
использует существующий `agent-fix-impact-receipt.v1`, а для high-risk
cross-check — `agent-cross-check-receipt.v1` с token/resource caps и без
обязательного USD-cost.

Bug Forensics recipes являются metadata над существующей receipt chain. Они
optional, выключены по умолчанию и не могут вводить competing defect-repair
receipt schemas.

Event feed и lifecycle progress view являются projection-only артефактами.
Они не запускают model calls, не тратят токены и не меняют workflow state.
