# Plugin updates and plan impact

[Русская версия](../ru/reference/plugin-updates.md)

Use update advice to distinguish a new release from a compatible active runtime.
Installed plugin files, loaded instructions, the running Python package and plan
contracts are separate identities. Missing observations stay `UNKNOWN`. Supplied
host version labels are declarations; matching labels do not attest compatibility.

The `plugin-update` commands check metadata, assess explicit plans and offer
manual native steps. They do not start a model, installer or background service.
Native installation, automatic notification hooks and `safe-auto` remain
unqualified. Their refusal is not proof of a successful update.

Start with a request:

```json
{"schemaVersion":"agent-plugin-update-request.v1","mode":"manual","channel":"stable"}
```

```sh
agent-lifecycle plugin-update check --request request.json --out available.json
agent-lifecycle plugin-update check --request request.json --cache updates.cache.json --out next-check.json
```

An exact `pin`, for example `v2.48.0`, is never moved to another release. A
prerelease needs an explicit target and channel choice. Discovery reads the
official GitHub plugin metadata and exact-version PyPI wheel/sdist metadata.
It binds the resolved commit and checks version, origin and publication shape.
Coherent metadata does not prove artifact contents or installation readiness.
A missing historical impact descriptor means compatibility is unknown.

Each invocation allows eight HTTP requests, ten seconds, one MiB aggregate and
256 KiB per response, without redirects or automatic retries. Cache cadence is
one hour and successful observations expire after 24 hours. Offline results keep
the last observation and its staleness; they do not cancel authorized work.
`off` starts no network operation. An unqualified notify trigger or `safe-auto`
request refuses before dispatch, even if an input asserts that it is qualified.

Metadata readers are bounded foreground Python helpers, with one launch attempt
per HTTP attempt and the same parent deadline. They run no host update command.
The report distinguishes these attempts from native host processes and actual
wire telemetry. Long release notes and package descriptions are excluded before
the update-wire field checks; the bounded raw response hash is retained. The
4,096-character field bound applies to the identity/publication fields consumed
by the advisor. Ignored text is never passed to a model or interpreted as code.

Give assessment an explicit inventory and a data-only target descriptor:

```json
{"schemaVersion":"agent-plugin-plan-inventory.v1","currentVersion":"2.47.0","plans":[{"manifest":"plans/feature/plan.manifest.json","lock":"plans/feature/plan.lock.json","state":"work/feature/run.state.json"}]}
```

```sh
agent-lifecycle plugin-update assess --request request.json --release release-impact.json --inventory inventory.json --repository-root . --out impact.json
```

Assessment reuses canonical plan verification. It reads at most 32 named plans,
64 declared files per plan, 256 KiB per file and eight MiB aggregate. It does not
search other projects, run validation commands or alter plans. Outputs are
limited to 256 KiB; a limit refuses instead of silently truncating a success.
Flat v1/v2 lock verification is supported within this input boundary. Scoped/v3
locks and `extensions.reviewPolicy` require a separate transitive evidence
closure; this assessment returns `UNKNOWN` before invoking that verifier. It
does not traverse their review/runtime inventories or launch Git readers.

Read structural and semantic results separately. `NO_IMPACT_WITHIN_COVERAGE`
applies only to the declared checked identifiers. Missing schema, command, path,
profile, host, quality, review, evidence or authority coverage stays `UNKNOWN`.
A version label, unchanged schema or empty change list cannot prove unchanged
meaning. Local descriptor content and publisher review labels are declarations,
not an independent audit or permission to install.

For DRAFT/REOPENED plans, an exact matching literal edit can be proposed without
applying it; changed meaning needs affected independent review. Keep frozen
plans and locks intact. Use a retained qualified runtime or reviewed amendment.
Defer activation for active or paused work. Preserve completed history, expenses,
original clocks and failed attempts. Unreadable state is never assumed idle.

Installation, session restart and observed verification are separate actions.
Read [host update boundaries](../adapters/plugin-updates.md) before an update.
ALK cannot veto unrelated host background updates or promise cache retention.
