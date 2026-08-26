# Evidence plan

## EV25-CONTRACT

Every state transition is idempotent, source-bound and separate from ALK workflow authority. Parent/child lineage and per-attempt artifact namespaces are immutable.

## EV25-LIMITS

The core validates receipts and never performs provider or network calls. `external_jobs.py` composes the existing read-only `run_process` / `ProcessGroupOwner` boundary. Mutable state is private local adapter state under `.alk/external-jobs/<jobId>/attempt-<n>/` by default, with injectable temporary roots in tests, 0700/0600 permissions, normalized non-symlink paths and immutable attempt namespaces. Compose the existing private-file helpers and reject empty, dot, dot-dot, separator-bearing or escaping job and attempt identities. Cancellation terminates the process group; a terminal parent cancels every declared child, reports cleanup failure while any child remains live and keeps all partial child output diagnostic-only. Bounded waits expire and post-cancel writes invalidate the result. Existing process-cleanup and process-boundary tests must remain green without modification.

## EV25-ARTIFACTS

Large or sensitive payloads remain outside portable lifecycle evidence.

## EV25-QUALIFICATION

Run positive, boundary and adversarial fixtures. Mutate authority, lineage, limits, completeness, terminal verdict, parent-terminal child cancellation, cancellation cleanup, artifact namespace and replay independently; invalid cases must fail closed. A partial result, live declared child and `NO_FINAL_VERDICT` must have no acceptance effect.

## EV25-INCIDENTS

WS25-02 reproduces Case A and Case B from `activation-evidence.md` with synthetic no-provider fixtures. The fixtures prove process-group cleanup, immutable attempt namespaces, no mixed post-cancel output, bounded parent wait, terminal parent cancellation of every declared child and no acceptance effect from partial or unconsolidated child output. A separate negative fixture runs an ordinary workflow with the feature unused and proves that neither `.alk/external-jobs` nor any job state is created.

## EV25-DOCUMENTATION

Validate `docs/reference/external-tool-jobs.md` and `docs/ru/reference/external-tool-jobs.md`, navigation, terminology parity and optional-use examples.

## EV25-ACTIVATION

Bind every incident source digest in `activation-evidence.md`, prove `project.dependencies == []`, then run the complete predecessor, architecture, neutrality, documentation and publication gates against the exact candidate. Synthetic incident and ordinary-no-state reproduction is owned and accepted by WS25-02 through `EV25-INCIDENTS`.
