# Agent Lifecycle Kit

Agent Lifecycle Kit (ALK) - provider-neutral контрольный слой для coding agents.
Он превращает задачу в проверенную спецификацию, зафиксированный план,
ограниченные пакеты работ, проверку реализации и финальное подтверждение, чтобы
агент доводил работу до конца, а не останавливался на patch.

Главная цель проекта - закрывать задачу полностью, с максимально возможным качеством для выбранной модели, без оверинжиринга и с контролем расхода токенов.

**Лицензия:** Apache-2.0 · **Версия:** 1.29.0 · **Python:** 3.11-3.13

## Почему стоит попробовать

- Жизненный цикл ориентирован на завершение: план, выполнение, проверка и proof.
- Ядро нейтрально к провайдерам; команды конкретных CLI остаются в адаптерах.
- Маленькие и локальные модели получают компактный контекст, явный следующий шаг
  и детерминированные проверки.
- Дополнительные профили включаются только по типу задачи или уровню риска.
- Учёт расхода показывает токены и ресурсы; USD-cost необязателен и используется
  только когда metered-хост сам его сообщает.

## Области возможностей

### Планирование и выполнение

- Спецификация и план проверяются до начала реализации.
- Работа разбивается на пакеты с владельцем, границами записи и критериями
  приёмки.
- Выполнение, completion gate, блокировки, повторные попытки и финальное
  подтверждение фиксируются в структурированных артефактах.
- Draft-only task templates покрывают bugfix, idea-to-PR, PR review,
  merge-conflict repair и release-readiness задачи.

### Качество и подтверждение

- Проверка реализации сравнивает результат с frozen plan и acceptance evidence.
- Optional Bug Forensics profile для bug/regression repair задач фиксирует
  reproduction-before-fix, stable fingerprint, hypothesis ledger, minimal patch
  gate, same-fingerprint regression proof и reusable recipes.
- Proof-integrity слой для рискованных финальных подтверждений хранит stable
  findings, digest root cause, fix-impact receipts и hash chain.
- Optional cross-check, runtime policy и write-back receipts выключены по
  умолчанию и становятся blocking только если это явно задано в плане.

### Маршрутизация и расход

- Small-model packets, compact context profiles, objective snapshots и
  quality-cost learning помогают выбрать самый лёгкий безопасный режим.
- Phase resource measurements используют usage export envelope для токенов,
  длительности и resource counters без обязательного USD-cost.
- Экспорт использования показывает сессии, токены, ресурсы, digest
  подтверждений и необязательный host-reported `cost_usd`.

### Адаптеры и импорт

- Контракты адаптеров не смешивают детали конкретного хоста с lifecycle schemas.
- Release-time capability bench строит bounded probe plans и проверяет live
  receipts на drift без автоматического изменения maturity.
- Import mappers и issue-to-spec intake держат внешние workflow, agent dialects и
  тикеты как untrusted draft inputs.
- Episode retrieval ищет по receipt/session summaries с digest provenance и
  состоянием `chainVerified` или `chainUnchecked`.

### Операции

- Runner recovery receipts покрывают snapshot, restore, abandon, selected
  attempt, worker lease и heartbeat state.
- Sandbox receipts для рискованных задач описывают runtime containment отдельно
  от git write-scope.
- Диагностика готовности, event feeds и lifecycle progress views по умолчанию не
  пишут state и не запускают реальные модельные вызовы.

## Быстрый старт

Из исходного дерева:

```bash
python -m pip install -e .
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
agent-lifecycle adapter validate --descriptor adapters/codex/adapter.descriptor.json
```

Пошаговый пример: [Быстрый старт](quickstart.md).

## Обычный цикл

Обычный путь: спецификация -> frozen plan -> bounded work -> проверка реализации
-> final proof. Основные команды покрывают specification, plan, workflow, audit,
adapter, import, metrics, policy, diagnostics и runner state. Подробности:
[Справочник команд](reference/cli.md) и [источник правды](reference/source-of-truth.md).

## Зрелость адаптеров

`EXPERIMENTAL` означает, что адаптер описан в исходниках и проходит
повторяемые проверки без реального запуска, но продвижение не заявлено. Для
`VERIFIED` нужны ограниченная проверка на реальном хосте, калибровки расхода,
принятое обезличенное резюме подтверждений и финальное подтверждение
жизненного цикла для проверенного диапазона версий.

| Хост | Текущее заявление |
| --- | --- |
| Codex | `VERIFIED` для Codex CLI 0.145.0. Одобрение публичного каталога плагинов не заявлено. |
| Claude Code | `VERIFIED` для Claude Code 2.1.220. Одобрение официального каталога не заявлено. |
| OpenCode | `VERIFIED` для OpenCode CLI 1.18.9. Публикация в npm не заявлена. |
| Hermes | `VERIFIED` для Hermes Agent v0.19.0. Одобрение публичного каталога не заявлено. |
| Qwen Code | `VERIFIED` для Qwen Code 0.21.0 на проверенной host-local provider/model связке. Одобрение публичного пакета не заявлено. |
| Cursor | `EXPERIMENTAL`; безопасный локальный осмотр прошёл, но подтверждений из реального запуска недостаточно. |
| Gemini CLI | `EXPERIMENTAL`; локальная проверка на реальном вызове ограничена текущим уровнем Gemini Code Assist. |
| Goose | `VERIFIED` для Goose 1.45.0 на проверенной host-local provider/model связке. Одобрение публичного каталога не заявлено. |
| Kimi Code | `EXPERIMENTAL`; для проверки нужен настроенный провайдер и псевдоним модели. |
| Grok Build | `VERIFIED` для Grok Build 0.2.117 на проверенной host-local provider/model связке. Одобрение публичного каталога не заявлено. |
| OpenInterpreter | `VERIFIED` для `interpreter` 0.0.34 на проверенной host-local provider/model связке. Одобрение публичного каталога не заявлено. |
| Pi | `VERIFIED` для Pi 0.83.0 на проверенной host-local provider/model связке. Одобрение публичного каталога не заявлено. |

Подробнее: [Установка адаптеров](adapters/install.md) и
[матрица поддержки адаптеров](adapters/support-matrix.md).

## Карта контрактов

Публичная поверхность жизненного цикла описана схемами. Полный список stable
schema ids, правила совместимости, runner recovery receipts, cross-check
contracts, Bug Forensics contracts и usage export details находятся в
[Публичных контрактах](reference/public-contracts.md).

## Границы проекта

- Ядро остаётся нейтральным к провайдерам. Команды конкретного хоста и выбор
  модели живут в адаптерах или локальных профилях.
- Маленькие модели получают компактные пакеты, детерминированные проверки и
  явные следующие действия.
- Большие модели проходят те же обязательные проверки качества; более сильное
  рассуждение не заменяет подтверждающие артефакты.
- Пробный запуск, заготовка, осмотр или синтетический прогон не повышают
  зрелость адаптера.
- Публичные заявления релиза опираются только на отслеживаемые файлы и
  обезличенные резюме подтверждений.
- Git write-scope ограничивает пути репозитория; sandbox receipts описывают
  runtime containment и могут оставаться `UNKNOWN` до отдельной проверки.
- Внешние dialect imports и retrieved episodes помогают с контекстом, но не
  заменяют проверенные ALK source-of-truth artifacts.
- Optional cross-check, runtime policy и write-back receipts добавляют evidence
  только при запросе задачи или плана; это не default multi-model execution.

## Документы

- [Быстрый старт](quickstart.md)
- [Issue to specification drafts](issue-to-spec.md)
- [Установка адаптеров](adapters/install.md)
- [Матрица поддержки адаптеров](adapters/support-matrix.md)
- [Справочник команд](reference/cli.md)
- [Источник правды](reference/source-of-truth.md)
- [Публичные контракты](reference/public-contracts.md)
- [Диагностика готовности](reference/readiness-diagnostics.md)
- [Small-model packets](reference/small-model-packets.md), [adaptive policy](reference/adaptive-lifecycle-policy.md), [quality-cost learning](reference/quality-cost-learning.md) и [учёт расхода жизненного цикла](reference/lifecycle-cost.md)
- [Экспорт использования](reference/usage-export.md)
- [Целостность подтверждений](reference/evidence-integrity.md)
- [Read-only status views](reference/read-only-status-view.md)
- [Sandbox boundaries](reference/sandbox-boundaries.md)
- [Import mappers](reference/import-mappers.md)
- [Episode retrieval](reference/episode-retrieval.md)
- [Runner recovery](reference/runner-recovery.md)
- [Cross-check profile](reference/cross-check-profile.md)
- [Bug Forensics profile](reference/bug-forensics.md)
- [Bug Forensics context budget](reference/bug-forensics-context-budget.md)
- [Task templates](reference/task-templates.md)
- [Безопасность релиза](security/release-security.md)

## Лицензия

Apache-2.0. Текст лицензии находится в корне репозитория.
