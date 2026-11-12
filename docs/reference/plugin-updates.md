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
A missing historical impact descriptor means compatibility is unknown. A null
`sourceCommit` remains unresolved: offer returns `UNKNOWN` without commands.
Malformed non-null commits and mismatches with a declared trusted commit refuse.

Each invocation allows eight HTTP requests, ten seconds, one MiB aggregate and
256 KiB per response, without redirects or automatic retries. Cache cadence is
one hour per retained caller record and successful observations expire after
24 hours. Success and failure return an explicit cache with `lastAttemptAt`; a
failure also records `lastFailureReason` and preserves the original successful
`observedAt` and candidate. Before a first success, both are null. Retaining that
returned cache suppresses HTTP for one hour after the attempt, including failure,
and returns `UNAVAILABLE` or `STALE`. Legacy positive caches use `observedAt` as
the attempt time. This is no process lock or global scheduler: discarded records,
concurrent callers and separate processes have no shared cadence guarantee.
Offline results do not cancel authorized work.
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
64 declared files per plan, 256 KiB per file and eight MiB of unique input bytes.
Each contained path is charged once; repeated reads must match its first size
and hash, including across plans. `inputBytes` counts unique bytes, while
`readBytes` counts cumulative wrapper reads, excluding whole-verifier/host IO. It does not
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

The shipped descriptor deliberately retains `sourceCommit: null`. To bind a local
copy, preserve the exact canonical descriptor and discovery report, compare their
version and descriptor content, then create a separate file exclusively:

```sh
python - <<'PYTHON'
from pathlib import Path
from agent_lifecycle.contracts import canonical_bytes, load_json_object, sha256_hex
from agent_lifecycle.contracts.plugin_update_validation import (
    update_digest, validate_release_impact, validate_update_report,
)
source = Path("release-impact.json").read_bytes()
discovery = Path("available.json").read_bytes()
descriptor = validate_release_impact(load_json_object(source))
report = validate_update_report(load_json_object(discovery))
assert report["action"] == "check" and report["status"] in ("AVAILABLE", "CURRENT")
candidate = report["details"]["candidate"]
assert descriptor["sourceCommit"] is None
assert candidate["releaseImpact"] == descriptor
assert candidate["version"] == descriptor["version"]
derived = {**descriptor, "sourceCommit": update_digest(candidate["sourceCommit"], 40)}
body = canonical_bytes(validate_release_impact(derived)) + b"\n"
with Path("release-impact.observed.json").open("xb") as output:
    output.write(body)
print("canonical descriptor SHA256:", sha256_hex(source))
print("discovery report SHA256:", sha256_hex(discovery))
print("derived descriptor SHA256:", sha256_hex(body))
print("trust: DECLARED local derivation; no authority granted")
PYTHON
```

Use `--release release-impact.observed.json` for a fresh assessment under the same
request policy. Keep the printed hashes with both original inputs. The separate
copy binds the discovery commit, version and exact descriptor content; it remains
`DECLARED`, and the canonical source still has a null commit. The local report and
this recipe do not authenticate each other or grant installation authority.
