# Accounting platform support

Release 2.16 separates ALK filesystem guarantees from the capabilities of the
selected host. A successful storage or pipe check does not qualify a model
host, establish whole-host usage, or authorize protected financial closure.

| Boundary | POSIX | Windows / NTFS |
| --- | --- | --- |
| Private artifacts | Actual owner, mode and guarded paths | Actual token SID, owner/DACL and held paths |
| Authority reads | Held directories, regular files and bounded reads | Held Win32 handles, reparse refusal and bounded reads |
| Durable coordinator writes | Checked file and directory barriers | Checked file barriers and directory `FlushFileBuffers` |
| Local byte pipes | Existing descriptor readiness | Nonblocking anonymous byte pipes with finite waits |

Windows privacy uses real ACLs. ALK refuses unsafe existing permissions;
it does not treat Windows mode bits as POSIX permissions. Existing directory
identity, regular-file and hardlink checks remain part of the boundary.
Only the existing diagnostic exception for an unchanged `installation_id`
can restore its original readonly flag. It cannot repair an unsafe DACL or
accept a replacement file, changed contents or changed access policy.

An input receipt measures bytes accepted by an OS pipe. It does not prove
that the host consumed those bytes. Deadlines, cancellation, output bounds
and process cleanup remain obligations of the existing caller. Local Python
test processes and kernel probes do not qualify native Codex execution.

The cumulative ledger retains task/run costs, retries, checks, auditors and
coordinator activity within the admitted accounting boundary. Missing host
metrics remain unavailable (`null`); they never become zero. For current
Codex, bounded ALK input accounting does not establish a cap over every
host-owned model call. Routes require their own existing documented host
capabilities and qualification. Unsupported protected closure remains
`UNSUPPORTED_OPERATOR_ROUTE`.

Raw-detail retention remains 30 days after complete run closure, executed
by the scheduled ALK maintenance command. Unfinished runs retain their raw
obligations. Summaries, deduplication identities, pending holds and original
clocks survive cleanup or compaction; a filesystem check does not release them.

From a source checkout on Windows/NTFS, create a fresh witness with:

```text
python -B tools/release/validate_windows_primitives.py --repository-root . --evidence work/windows-primitives.json
```

The command refuses to overwrite an earlier result. Its receipt records the
actual runtime, filesystem, kernel checks and source hashes before and after.
A POSIX invocation cannot produce a Windows PASS. Evidence from an ARM64
SYSTEM VM describes that target only. Release acceptance additionally requires
the current source CI matrix and independent review; previous host receipts
keep their original source/version/mode bindings.
