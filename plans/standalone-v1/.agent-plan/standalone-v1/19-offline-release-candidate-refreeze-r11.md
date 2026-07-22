# Offline Release Candidate Refreeze r11

## Decision

The current executable run cannot satisfy production release gates that require
external signed baseline authority, live model calibration, and authenticated
nine-leg CI receipts. Continuing under the previous WS-14 contract would force
fabricated evidence, so revision 11 narrows WS-14 to an offline release
candidate and governance package.

## Included In WS-14

- release-candidate assembly inventory for the current source tree;
- local deterministic release verification;
- local neutrality scan over the current tree and release payload;
- support matrix that declares Codex, Claude Code, Cursor, Hermes, and OpenCode
  as `EXPERIMENTAL` unless later live evidence promotes them;
- documentation for installation, usage, adapter maturity, security, and
  production-promotion requirements;
- controller support for preserving compatible accepted tasks across refreeze.

## Deferred Production Promotion

The following gates remain required before any production or `VERIFIED` claim:

- signed external baseline authority;
- provider-neutral live model profile and host-attested live calibration;
- authenticated Ubuntu, macOS, and Windows matrix receipts for CPython 3.11,
  3.12, and 3.13;
- signed release neutrality over all refs, reflogs, reachable and unreachable
  objects, ignored files, and the committed content-addressed release
  generation.

Deferred gates are not treated as passed by the offline release-candidate.

## Refreeze Impact

- WS-01 through WS-13 and WS-16 are unchanged and may be preserved when their
  task contracts are compatible.
- WS-14 changes from production release proof to offline release-candidate
  assembly and governance.
- WS-15 final audit must verify offline release-candidate readiness and confirm
  that production/live claims remain blocked until external evidence exists.
