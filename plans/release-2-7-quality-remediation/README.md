# Release 2.7 pre-publication quality remediation

Status: `FROZEN CANDIDATE / REVISION 2 / S2 / EXACT-DIGEST REVIEW PENDING`

## Goal

Make the exact Release 2.7 candidate pass the mandatory `python-quality` CI
workflow without weakening any quality, architecture or security control.

## Trigger

Pull request #155 failed all four `Python quality` matrix jobs. A local replay
against the Release 2.6 base reproduced the same blocker set while all 1,993
tests passed. The failure was omitted from the original Release 2.7 validation
commands, so the already terminal workflow state cannot authorize further task
attempts.

## Scope

1. Remove all E501 findings from Release 2.7 changed source files reported by
   the current quality policy.
2. Remove all mypy findings from Release 2.7 changed source files reported by
   the current quality policy.
3. Preserve runtime behavior, canonical outputs, schema meaning, reviewer
   authority, quality floors and fail-closed validation.
4. Re-run the exact CI quality producer and validator against base revision
   `30e2f2a55a2b8d959fa22b884e122952a2711ff7`.
5. Re-run focused tests, the full suite, architecture gates and neutrality.
6. Prove path authority through the workflow ownership receipt and final
   implementation audit; a declared forbidden path is not only documentation.

## Non-goals

- changing `policy/python-quality.json` or accepting new baseline findings;
- broad formatting or typing cleanup outside the reported Release 2.7 paths;
- changing public contracts, output data, thresholds, authority or release
  metadata;
- editing or replacing the completed `work/release-2-7/run.state.json`;
- treating a local PASS as a substitute for the GitHub pull-request checks.
- weakening, deleting or replacing existing test assertions; writable tests may
  only add or tighten behavior-preservation coverage when implementation needs
  it.

## Completion

The package is complete only when its independent implementation audit is
ACCEPTED, all local gates pass, and PR #155 reports a green `python-quality`
matrix on Python 3.11 through 3.14.
