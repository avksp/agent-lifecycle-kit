# Evidence plan

## EV26-LOCK

First finalize a FROZEN fixture whose `planReview.report` and review `planFiles` path are already declared while the report is absent. Hash those exact manifest bytes, write the matching independent review into the pre-declared path, and only then invoke lock creation. Mutate manifest status, review independence, verdict, open Medium/High findings, package id, plan revision, exact reviewed manifest digest, manifest bytes, `planFiles`, undeclared file, symlink, output path and existing output independently. Assert that every invalid case writes nothing, replacement never occurs, the command cannot change manifest or review bytes, and the produced lock passes both `plan check` and `plan verify` with complete filesystem verification. The binding implementation must stay in WS26-01-owned `freeze/package_integrity.py`; `review/validation.py` remains unchanged.

## EV26-PHASES

Use a tracked fixture with planning, implementation and audit phases. Compare CLI output byte-for-byte with `build_phase_resource_measurement`. Mutate token types, negative duration, unsupported resource fields, monetary fields, source digest, 256/257 phase-count boundary in both build and validation paths, and the shared 1 MiB canonical JSON input-byte boundary.

## EV26-ACCOUNTING

Add tracked synthetic equivalents of the three observed shapes: a complete phase measurement, parallel reviewers with wall time lower than summed compute, and a release containing unavailable implementation telemetry plus a non-additive multi-release goal snapshot. Run both the Python API and `metrics release-accounting`; assert digest-equivalent output, exact totals, exclusions, availability states and no-replace writes. Feed phase resources to `cost-report` and assert declared token totals rather than JSON-size estimates.

## EV26-PROVENANCE

Mutate core version, host plugin version, skill package version, run ALK version, source revision and measurement digest independently. Each mismatch remains reported and cannot become `ATTESTED` merely because another version field matches. Mutating provenance after generation must invalidate the accounting digest.

## EV26-HANDOFF

Extend and execute `tests/planning/test_continuity.py` as the tracked no-model fixture through planning checkpoint, task-packet implementation session, independent audit session and acceptance session. Each continuation must fit declared context limits and require only hash-bound artifacts, not a raw transcript. The recipe must distinguish commands run by the operator from authority-bearing workflow transitions.

## EV26-PUBLICATION

Run the full test suite, the explicit locked `run_python_quality.py` plus `validate_python_quality.py` evidence route, module/package dependency and complexity gates, neutrality, documentation, schema registry and publication validation at the exact candidate. Do not lower a baseline to obtain a pass.
