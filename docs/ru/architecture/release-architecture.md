# Архитектура выпуска

Архитектура выпуска состоит из двух этапов:

1. Локальный кандидат выпуска.
2. Продвижение в production.

Локальный кандидат воспроизводим. Он собирает адресуемый по содержимому inventory исходников, документации, общих skills, адаптеров, conformance-данных, тестов и файлов управления. Он проверяет support matrix и договор отложенного продвижения, не утверждая внешнее выполнение. Он также проверяет public contract policy: идентификаторы схем, CLI JSON envelopes и стабильные коды ошибок должны оставаться предсказуемыми для адаптеров и release scripts.

Inventory и evidence кандидата создаются в игнорируемом `release/candidate/`. Это производные результаты, а не исходная authority; чистый checkout восстанавливает их без committed release artifacts. `CHANGELOG.md` содержит историю выпусков исходного дерева; immutable GitHub Releases фиксируют опубликованные версии.

Продвижение в production выполняется отдельно. Оно требует подписанных внешних receipts выполнения platform matrix, release neutrality, live host lifecycle conformance и live cost calibration. Отсутствующая внешняя authority блокирует продвижение; её нельзя превратить в локальный PASS.

Live conformance и calibration представлены профилями и validators, а не локальными model benchmarks. Локальный выпуск поставляет contracts и validators; promotion добавляет подписанные live receipts. Validators отвергают synthetic replay, отсутствие usage attestations, обход host-operation envelope, неполный охват сценариев/cohorts и превышение бюджета, включая отдельный сценарий 4k-strict compact-context.

## Условия выполнения

До любого заявления о production promotion локальные gates проверяют:

- human acceptance checklists против frozen manifest;
- захват adapter progress как нейтральных потоков `agent-adapter-event.v1`;
- отказ task acceptance для unowned, read-only или forbidden changed files;
- привязку каждой попытки к launch baseline и обязательную reconciliation при drift;
- optional multi-review quorum только при явном opt-in frozen plan для этой фазы;
- completion signal или явный evidence-bound waiver до finalization;
- matching completion-check receipt для принятого `completionCheck` до записи final proof;
- паузу human-only action до появления external-action receipt.

Эти gates подтверждают локальное завершение, но не повышают адаптер до `VERIFIED`. Promotion по-прежнему требует отдельных live conformance и calibration receipts.

## Доказательства ресурсов

Lifecycle cost accounting — release evidence дисциплины ресурсов. Отчёт разделяет implementation, product validation, pipeline compliance и coordination: затраты собственного процесса ALK должны быть видимы рядом с работой над задачей.

Strict и release modes могут выполнять более глубокие проверки, но превышение pipeline cost требует явной причины. Cost receipt не заменяет tests, review, support matrix validation или final proof.
