---
name: bug-forensics
description: Optional defect-repair profile for bug search, regression repair, flaky failure investigation, incidents, and security-bug fixes.
---

# Bug Forensics

Use this skill only when the task explicitly asks to find or repair a bug,
regression, flaky failure, incident, or security bug. The profile is optional
and disabled by default for ordinary feature work.

## Contract

Before accepting a patch, collect schema-backed evidence for:

- symptom;
- reproduction before modification;
- stable failure fingerprint;
- hypothesis ledger with accepted and rejected hypotheses;
- root cause;
- minimal patch;
- regression proof for the same fingerprint;
- no collateral damage through the canonical fix-impact receipt.

## Inputs

Required phase-1 receipts:

- `agent-bug-reproduction-receipt.v1`;
- `agent-failure-fingerprint.v1`;
- `agent-bug-hypothesis-ledger.v1`;
- `agent-regression-proof-receipt.v1`;
- `agent-fix-impact-receipt.v1`.

Reuse `agent-fix-impact-receipt.v1` for behavior impact. Do not create a
bug-specific competing fix-impact schema.

## Gates

- Reproduction must be red before any code modification.
- Regression proof must show the same fingerprint red before and green after.
- Minimal patch gate must justify any file outside the suspect scope.
- Cross-check is advisory unless the frozen plan explicitly opts into blocking
  use. When used, reuse `agent-cross-check-receipt.v1` with token/resource
  caps.
- Suspect graph, flake detector, and bug-class classifier are phase-2 features
  and must not block the v1 profile unless a later plan enables them.

## Compact Context

For compact hosts, include only the active bug packet, reproduction command,
fingerprint fields, current hypotheses, suspect/write scope, and validation
receipts. Summarize logs by digest and short failure pattern instead of copying
large traces.
