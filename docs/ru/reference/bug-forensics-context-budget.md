# Bug Forensics Context Budget

Bug Forensics должен помещаться в compact context без копирования больших
логов. Бюджет задаётся в tokens/resources, обязательный USD-cost не нужен.

В compact packet включаются:

- активная bug-задача и acceptance criteria;
- failing reproduction command и короткий failure pattern;
- failure fingerprint fields и digest;
- hypothesis ledger, максимум 12 записей;
- suspect scope, write scope и minimal-patch justification;
- root-cause digest и fix-impact receipt digest;
- regression proof command до и после фикса;
- optional cross-check receipt digest, если он был включён планом.

Default caps:

- active packet: 9000 tokens;
- evidence summary: 4000 tokens;
- hypothesis ledger entries: 12;
- artifact digest refs: 20.

Полные логи остаются artifact files. В контекст достаточно включать path,
sha256, byte count, верхний stack frame, exception/assertion и стабильный log
pattern.
