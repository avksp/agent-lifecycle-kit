# Договор переходов workflow

Release 2.0 заменяет прежнюю поверхность controlled-runner transitions машиной состояний workflow. Durable workflow state — единственная authority для authorization, task attempts, budgets, result acceptance, remediation и finalization.

## Текущая authority

Текущие mutations используют workflow commands и несут operation id, expected state revision, source revision и frozen-plan lineage. Активный execution receipt — `agent-workflow-run-receipt.v1`.

Прежние runner action names остаются в read-only compatibility catalog: вызывающая сторона получает стабильный replacement или migration route. Каталог не является dispatcher и не может менять состояние.

## Историческая граница

Runner state, transition, snapshot и recovery documents до 2.0 — historical artifacts. `workflow migrate-runner-artifact` проверяет и преобразует их с bounded input, source immutability, private no-replace output и `authorityClaimed: false`. Он никогда не восстанавливает отсутствующую lineage и не выдаёт execution authority.

Compatibility converter обязателен в течение всей 2.x. Его удаление требует независимого compatibility audit и решения о будущем major version; ни один minor release 2.x не может вернуть вторую execution authority.
