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

`agent-cross-check-receipt.v1` фиксирует subject, reviewer, findings, budget
cap и фактическое usage. Валидация падает, если:

- digest профиля не совпадает;
- usage превышает cap;
- blocking cross-check заявлен без opt-in в плане;
- live calls заявлены, но профиль их не разрешает;
- используются monetary budget fields.

Такой профиль полезен для S2, security, release и bug-fix задач, но обычные
задачи остаются на стандартном lifecycle path.
