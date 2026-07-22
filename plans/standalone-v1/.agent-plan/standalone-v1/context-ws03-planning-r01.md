# WS-03 Planning Context Projection

The frozen packet carries the exact REQ-SDD statement, acceptance, evidence,
ownership and writes. Implement the following portable planning lifecycle.

- Classify S0 only for one bounded low-risk mechanical stream, S1 for one
  standard owner, and S2 for multi-owner or architecture, security,
  performance, browser or external-environment risk.
- S2 requires a product specification, independent append-only specification
  reviews, READY_TO_PLAN, freeze receipt lineage and inclusion in the common
  plan lock before plan review/freeze.
- Plan author and plan reviewer are independent. CHANGES_REQUIRED revisions are
  append-only and every report links to the immediately previous report.
- Freeze only a decision-complete plan with exact DAG, ownership, writes,
  forbidden writes, commands, evidence, budgets, controller gates, developer
  overview and implementation-audit hook.
- Any contract, architecture or write-set drift reopens the package and
  requires review/refreeze; no worker or auditor silently edits a frozen plan.
- Hash and root handling must be portable, canonical and fail closed.

Tests cover S0/S1/S2 boundaries, ancestry breaks, stale reviews, self-review,
hash drift, refreeze, exact roots and forbidden post-freeze mutation.
