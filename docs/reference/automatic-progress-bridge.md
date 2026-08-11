# Adapter progress bridge

The adapter progress bridge lets a host wrapper show ALK lifecycle progress in
the terminal while the host still owns model execution. It is a display layer
over existing workflow state, usage receipts and change-summary receipts.

The bridge is intentionally small:

- `agent-lifecycle report progress --terminal` prints the current lifecycle
  rows as text instead of JSON.
- `agent-lifecycle report progress-bridge` returns
  `agent-progress-bridge-receipt.v1` for adapter wrappers.
- `agent-progress-bridge-config.v1` records an adapter support declaration.
- `agent-progress-hook-policy.v1` and `agent-progress-hook-receipt.v1` record
  opt-in hooks from ALK-managed workflow commands.
- Existing JSON commands stay the default machine contract.

The bridge is not source of truth. Workflow state remains authoritative. The
bridge reports `readOnly: true`, `modelCallsStarted: false`,
`stateWritten: false`, `tokenSpendForProgress: false` and
`hostTelemetryParsedInCore: false`.

## Managed workflow hooks

ALK-managed workflow commands can emit progress after a successful transition:

```bash
agent-lifecycle workflow run \
  --state <workflow-state.json> \
  --manifest <plan.manifest.json> \
  --operation-id <id> \
  --expected-revision <n> \
  --source-revision <git-sha> \
  --progress-hook stderr
```

The supported commands are `workflow run`, `workflow task-result`,
`workflow task-accept` and `workflow finalize`. The hook is off by default.
`--progress-hook stderr` writes terminal progress to stderr. `--progress-hook
receipt --progress-receipt <path>` writes `agent-progress-hook-receipt.v1`
without changing stdout. Wrapper scripts may set `ALK_PROGRESS_HOOK=stderr`,
but flags are the canonical interface.

`AUTO` progress requires proof that the command is ALK-managed. Installing a
plugin or skill is not lifecycle proof by itself.

## Support levels

Adapters document one support level:

| Level | Meaning |
| --- | --- |
| `AUTO` | The host integration can call the bridge from an ALK-managed command or shipped wrapper with proof. |
| `WATCH` | The operator or wrapper can run a side terminal watch. |
| `MANUAL` | The operator can run a one-shot progress command. |
| `UNSUPPORTED` | No supported hook or documented wrapper exists yet. |

Progress support is a separate capability. A `VERIFIED` adapter can still be
`MANUAL` for progress, and an `EXPERIMENTAL` adapter can document a safe manual
command.

## Commands

JSON progress remains the default:

```bash
agent-lifecycle report progress --state <workflow-state.json>
```

Terminal output is explicit:

```bash
agent-lifecycle report progress --state <workflow-state.json> --terminal
```

Adapter wrappers use the bridge receipt when they need a stable JSON envelope
and terminal text together:

```bash
agent-lifecycle report progress-bridge \
  --adapter codex \
  --support-level WATCH \
  --hook-point side-terminal-watch \
  --state <workflow-state.json> \
  --usage-receipt <usage.json> \
  --change-summary <changes.json>
```

Add `--terminal` to print only the terminal text. Add `--out <receipt.json>` to
persist the JSON receipt while printing text.

## Token and change counters

Token counters use only host-attested usage receipts. Unknown or unattested
usage renders as `↑?/↓? tok`; ALK does not infer missing counts. Change
counters come from `agent-change-summary-receipt.v1`, which is built by the
dedicated Git helper.

## Host responsibility

Host adapters remain responsible for native launches, cancellation, waits,
provider/model telemetry and any native hook. Core ALK does not patch host
CLIs, run a background daemon, inject prompts, or parse host-specific telemetry.
