# Bug Forensics Context Budget

Bug Forensics can be run on compact hosts if the packet stays evidence-focused.
The default profile uses token/resource caps rather than mandatory USD cost.

Recommended compact packet contents:

- active bug task and acceptance criteria;
- failing reproduction command and short failure pattern;
- failure fingerprint fields and digest;
- current hypothesis ledger, capped to 12 entries;
- suspect scope, write scope and minimal-patch justification;
- root-cause digest and fix-impact receipt digest;
- regression proof command before and after the fix;
- optional cross-check receipt digest when a plan requested it.

Default context caps:

- active packet: 9000 tokens;
- evidence summary: 4000 tokens;
- hypothesis ledger entries: 12;
- artifact digest references: 20.

Large logs should be summarized by path, sha256, byte count, top stack frame,
exception/assertion and stable log pattern. Full logs remain artifacts and do
not need to be copied into the compact packet.
