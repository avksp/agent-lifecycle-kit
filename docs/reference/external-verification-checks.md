# External verification checks

ALK can record the result of an optional project-owned architecture or dependency
check. The check is an input to review, not a second lifecycle authority.

## Run a built-in check

The 1.88 package includes three bounded profiles:

- `import-boundaries` runs the project-owned `import-linter` check;
- `module-dependencies` runs the project-owned `tach` check;
- `declared-dependencies` runs the project-owned `deptry` check.

The analyzer is not bundled with ALK. Install and configure it in the project
that owns the check, then run it with the exact frozen plan and lock identities:

```bash
agent-lifecycle quality external-check \
  --check-id import-boundaries \
  --plan-digest <64-hex-digest> \
  --plan-lock-digest <64-hex-digest> \
  --operation-id external-check-001 \
  --out work/external-check.json
```

Use `--profile <path>` when the project has an explicitly reviewed profile. A
profile contains an executable name and an argv list, never a shell command
string. `--config <path>` may select the project configuration, while the
source snapshot is captured by ALK from the project tree.

## Result and trust boundary

The output contains a descriptor, invocation, normalized result and audit. The
result binds the analyzer identity and version, configuration digest, source
revision and file-set digest, plan and lock digests, bounded finding IDs and
locations, timeout and output limits, and cleanup status.

The possible operational states are `PASS`, `FAIL` and `UNAVAILABLE`.
`UNAVAILABLE` is returned when the optional analyzer is absent or its result is
incomplete. A changed source tree, descriptor, configuration, plan or lock
causes a blocking check to fail closed. ALK also compares the source snapshot
after the process exits so a check that changes the tree cannot become eligible.

Raw stdout and stderr are not persisted as result evidence. Output is bounded
and redacted before findings are normalized. The check runs through the
shell-free process boundary with explicit argv, working directory, timeout,
environment and byte limits.

An external result cannot freeze a plan, accept a task, authorize a run or
promote a release. `authorityClaimed` remains `false`. A plan may require a
clean external check as one acceptance input only when the frozen plan declares
the exact tool, configuration and source identities and the resulting evidence
is independently reviewed. Presence of a profile or a `PASS` string is not a
support claim and is not sufficient for acceptance by itself.

## Installation and portability

The three profile files have identical repository and package-data copies, so
the built-in profiles work outside the ALK checkout. ALK keeps zero runtime
dependencies: analyzer installation, configuration and upgrades remain the
responsibility of the project that invokes the check. Missing tools therefore
produce `UNAVAILABLE`, rather than silently skipping a required check or
claiming success.

External checks extend evidence for architecture and dependency policy. They do
not replace ALK's plan, ownership, security, source-freshness, review or final
audit gates.
