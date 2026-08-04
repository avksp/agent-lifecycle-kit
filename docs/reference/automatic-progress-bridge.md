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
- Existing JSON commands stay the default machine contract.

The bridge is not source of truth. Workflow state remains authoritative. The
bridge reports `readOnly: true`, `modelCallsStarted: false`,
`stateWritten: false`, `tokenSpendForProgress: false` and
`hostTelemetryParsedInCore: false`.

## Support levels

Adapters document one support level:

| Level | Meaning |
| --- | --- |
| `AUTO` | The host integration can call the bridge from a native lifecycle hook. |
| `WATCH` | The operator or wrapper can run a side terminal watch. |
| `MANUAL` | The operator can run a one-shot progress command. |
| `UNSUPPORTED` | No supported hook or documented wrapper exists yet. |

The level is not a maturity claim. A `VERIFIED` adapter can still be `MANUAL`
for progress, and an `EXPERIMENTAL` adapter can document a safe manual command.

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
provider/model telemetry and any automatic hook. Core ALK does not patch host
CLIs, run a background daemon, inject prompts, or parse host-specific telemetry.
