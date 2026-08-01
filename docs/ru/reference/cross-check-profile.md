# Optional Cross-Check Profile

Generic cross-check profile позволяет плану запросить дополнительную проверку
для рискованной задачи, не включая multi-model review в базовый жизненный цикл.

`agent-cross-check-profile.v1` всегда:

- `OPTIONAL`;
- выключен по умолчанию;
- включается только явно;
- advisory by default;
- становится blocking только при явном opt-in в плане;
- ограничен по tokens, invocations и wall-clock resources;
- не является canonical USD-cost поверхностью.

## Receipts

`agent-cross-check-receipt.v1` фиксирует subject, reviewer, findings,
independence evidence, budget cap и фактическое usage. Валидация падает, если:

- digest профиля не совпадает;
- usage превышает cap;
- blocking cross-check заявлен без opt-in в плане;
- independence требуется, но не подтверждается нейтральными identity hashes;
- live calls заявлены, но профиль их не разрешает;
- используются monetary budget fields.

Independence provider-neutral: receipt сравнивает только `hostIdentityHash` и
`modelIdentityHash`. Имена провайдеров, моделей и аккаунтов не являются
canonical contract fields.

Такой профиль полезен для S2, security, release и bug-fix задач, но обычные
задачи остаются на стандартном lifecycle path.
