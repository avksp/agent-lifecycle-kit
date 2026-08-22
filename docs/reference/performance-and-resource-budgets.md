# Performance and resource budgets

Release 1.78 improves the cost of repeated local ALK commands while preserving
the security, compatibility and evidence boundaries of the lifecycle. The
figures collected by the performance harness describe one environment; they
are not a universal speed promise.

## What Release 1.78 measures

The revision-bound baseline records the source revision, dirty-tree state,
platform, Python implementation, CPU count, warm-up, samples, bounded output
and operation counters. The default operations are CLI `version`, the
`tracked-release` neutrality scan and canonical digest calculation.

The release also validates the properties that matter more than a wall-clock
number:

- Ed25519 output remains compatible with RFC 8032 vectors, accepted receipt
  fixtures and strict malformed-input handling.
- Full-repository neutrality scanning uses bounded Git batch streams and keeps
  the accepted object inventory and byte representation.
- Deny-rule matching preserves rule identifiers, findings, order, duplicates
  and regular-expression behavior.
- Worktree identity uses bounded streaming reads, stable identity checks and
  both before/after captures.
- Process cleanup, output limits, timeout behavior and the `shell=False`
  boundary remain unchanged.
- The `version` command avoids importing host-launch, process and neutrality
  scanning modules before a command family is selected.

## Hard gates and advisory measurements

Hard gates determine whether evidence is acceptable. Timing, memory and
platform-specific counters are comparative information unless a plan gives
them an explicit acceptance threshold. An incomplete, stale, mixed-environment
or unbounded measurement cannot be turned into a passing result by reporting a
better number.

The only performance threshold in the 1.78 acceptance contract is the
interleaved Ed25519 comparison: optimized public-key derivation, signing and
verification medians must each be no more than 20% of the frozen affine
reference median. This comparison does not make a constant-time or
side-channel-resistance claim.

## Resource ceilings

The typed runtime ceilings are defined in
`src/agent_lifecycle/contracts/performance_limits.py`. The release policy in
`policy/performance-budgets.json` may choose a lower value, never a higher one.

| Area | Ceiling | Meaning |
| --- | ---: | --- |
| Git processes in a full scan | 4 by policy; the optimized route uses 2 | Process count does not grow with object count. |
| Git objects | 1,000,000 | Inventory growth fails closed at the limit. |
| Git inventory | 128 MiB | The `rev-list` inventory is consumed incrementally. |
| One Git object | 16 MiB | Oversized objects are incomplete, not silently skipped. |
| Expanded Git data | 4 GiB | Aggregate expansion is bounded. |
| Batch framing | 128 MiB | Protocol framing is bounded separately from object data. |
| Full-scan wall time | 600 seconds | A deadline, not a permission to return partial proof. |
| Untracked files | 100,000 files / 4 GiB | Worktree identity refuses unbounded input. |
| Hash chunk | 256 KiB | Ordinary files are hashed with bounded memory. |
| Deny rules | 1,024 rules / 4 KiB each / 1 MiB aggregate | Authority and policy inputs are checked together. |
| Simple literal rules | 64 | Larger accepted literal sets use the differential matcher. |
| Linux group samples | 4 per second | Expensive process-table enumeration has its own cadence. |
| Evidence per run | 96 MiB | Evidence cannot grow without a bound. |

When a limit, protocol check, stable-read check or cleanup check fails, ALK
returns structured incomplete or blocked evidence. It does not omit the bad
input and present the remaining data as complete proof.

## Safe optimization boundaries

The following changes are allowed because they preserve the same observable
contracts: extended-coordinate Ed25519 arithmetic with equivalent vectors,
long-lived bounded Git batch processes, a differential literal matcher,
chunked untracked-file hashing, a slower cadence for expensive Linux group
counts and lazy imports after command selection.

The following remain prohibited: caching signatures, profiles or scan results;
removing either worktree capture; skipping stable-read checks; accepting
truncated or oversized Git responses; raising timeout or output limits; using
`shell=True`; weakening Ed25519 decoding; disabling secret redaction; or
turning a timing result into authority over a plan or release.

## Operator-visible statuses

- `PASS` means the declared semantic and resource checks passed.
- `NO_RECOMMENDATION` means comparable performance evidence was not available;
  it is not a speed claim and does not replace required proof.
- `INCOMPLETE` means the scanner or measurement hit a limit, protocol error,
  unstable input or another fail-closed condition.
- `BLOCKED` means a required security, ownership, compatibility or cleanup
  condition was not satisfied.

## Reproduce the checks

Run from the repository checkout with Python 3.11-3.14:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 tools/performance/run_performance_baseline.py \
  --policy policy/performance-budgets.json \
  --repository-root . \
  --output work/performance-baseline.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
python3 tools/release/validate_performance_evidence.py \
  --policy policy/performance-budgets.json \
  --input work/performance-baseline.json \
  --evidence work/performance-validation.json
```

Use `tracked-release` for the normal release neutrality check. Use
`full-repository` only when the plan explicitly requires historical Git object
coverage. Its limits and incomplete results are part of the evidence contract.

Performance evidence contains digests, counts and bounded summaries. It must
not persist prompts, host output, environment secrets, raw Git object contents
or private local paths. See [neutrality scanning](neutrality.md),
[production resource and security](../guides/production-resource-security.md)
and the [system architecture](../architecture/system-architecture.md).

[Русская версия этой страницы](../ru/reference/performance-and-resource-budgets.md).
