# Retaining and removing execution details

ALK keeps cumulative financial totals, deduplication identities, closure records
and hash-only summaries. Raw requests, diagnostics and credential-free captured
configuration become eligible for logical removal **30 days after authoritative
full financial closure**. Finishing a worker or accepting a task does not start
that clock. Active runs, unresolved usage and financial exceptions keep their
details. This is file removal, not physical media erasure.

Run the existing CLI under the same operating-system account:

```bash
agent-lifecycle workflow maintenance \
  --authority /absolute/private/root/maintenance-authority.json \
  --authority-sha <exact-raw-sha256> \
  --candidate-limit 32 --deadline <future-UTC-instant>
```

The authority and its private `.writer.json` sidecar must already belong to the
journal writer. It binds the canonical private root, journal identity and file,
writer, storage version, reviewed manifest and lock. Pin its raw SHA in the run
evidence and schedule. Do not generate a substitute authority to force cleanup.
There is no `--journal` or `--private-root` override.

Each invocation has its own original finite deadline; ALK also limits its
maintenance work to 60 seconds. An hourly schedule must compute a fresh deadline
when that invocation starts. Reusing a literal expired timestamp cannot work.
That maintenance deadline does not renew a task or release deadline.

## Hourly scheduling on macOS

Use the absolute Python executable from the ALK environment and keep its source
or installed package version pinned. Save the following small wrapper in a
private directory, replace the three example paths/digest, and make the file
executable by its owner only. A source checkout may set an exact `PYTHONPATH` in
the LaunchAgent; an installed environment already supplies the package.

```python alk-maintenance-wrapper
from datetime import UTC, datetime, timedelta
import os
import sys

authority = "/absolute/private/root/maintenance-authority.json"
authority_sha = "<exact-64-hex-sha256>"
deadline = (datetime.now(UTC) + timedelta(seconds=45)).isoformat()
os.execv(sys.executable, [
    sys.executable, "-B", "-m", "agent_lifecycle", "workflow", "maintenance",
    "--authority", authority, "--authority-sha", authority_sha,
    "--candidate-limit", "32", "--deadline", deadline,
])
```

Install a user LaunchAgent under `~/Library/LaunchAgents/` with a unique label,
`ProgramArguments` containing the absolute Python and wrapper paths,
`StartInterval` set to `3600`, and private `StandardOutPath`/`StandardErrorPath`.
Do not use `KeepAlive`: a refusal must not create an immediate retry loop.
Load it with `launchctl bootstrap gui/$(id -u) <absolute-plist-path>` and inspect
`launchctl print gui/$(id -u)/<label>`. The readback must identify the installed
command, hourly interval and exact configuration. A manual `launchctl kickstart`
can exercise that installed entry without waiting an hour.

A user agent runs while that user's session is available. Sleep, logout,
scheduler failure and missed runs can delay cleanup. Monitor the actual receipts
and outstanding due obligations; an installed plist alone is not readiness.
To stop a particular schedule, use `launchctl bootout` for its exact service and
remove only that schedule's plist/wrapper. Keep journal and financial history.

Apple documents the scheduler in [Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).
The installed system's `man launchctl` and `man launchd.plist` describe its exact
commands and keys.

## Other platforms and refusal

Linux may invoke the same pinned wrapper through an hourly user timer. Windows
may schedule the same command, but the current raw-deletion implementation
requires POSIX descriptor-relative, no-follow operations. It refuses an
unsupported platform before opening the authority or deleting a file. A timer,
task definition or documentation alone does not qualify a platform. Enable
cleanup readiness only after actual installed-target observations establish
safe permissions, file identities and removal on that target.

`NOT_DUE` and `RUN_NOT_FULLY_CLOSED` preserve details. A due obligation left
pending for more than two hours becomes `OVERDUE`. A refusal or partial result
must remain visible and prevents retention readiness. Resolve its exact cause
before an explicitly bounded recovery; keep the original failure and expense.
Successful recovery removes every declared original/staging raw file and
records `DONE`, while totals, deduplication and closure summaries remain usable.

## Release qualification and host limits

The Release 2.16 selected Codex route is limited to ALK-controlled input on the
observed Codex CLI 0.162.1 configuration, using a private `CODEX_HOME` with the
documented `features.apps=false` setting. Whole-host input and financial usage
remain unavailable. Strong A5 protection and protected operator closing refuse
where that host cannot establish the required boundary. The twelve adapter
source profiles describe capability limits; they do not establish twelve
working native integrations or complete financial host enforcement.

The installed-target release probe uses an isolated, explicitly labelled
financial fixture journal and real scheduler/CLI processes. Historical fixture
preparation is separate from maintenance: the scheduler and deletion command
always use real current UTC. A local fixture receipt cannot close a production
run, release a hold or authorize deletion from an unrelated journal.
