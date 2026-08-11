# OpenInterpreter Adapter

OpenInterpreter is represented as a host-specific `VERIFIED` secondary adapter
for `interpreter` 0.0.34 on the tested host-local provider/model binding. ALK
owns the portable lifecycle envelopes; the adapter owns host-specific launch,
wait, cancel, event and usage mapping.

Tracked source artifacts:

- `adapters/openinterpreter/adapter.descriptor.json`
- `adapters/openinterpreter/capabilities.manifest.json`
- `conformance/adapters/openinterpreter/offline-baseline.json`
- `tools/live_hosts/openinterpreter_harness.py`

The source tree contains deterministic offline conformance, a bounded JSONL live
harness and a redacted local live evidence summary. It does not claim public
package or directory approval, and no production promotion claim is made.

The live harness uses the shared JSON CLI receipt loop for host conformance,
calibration, budget checks, diagnostics and post-invocation worktree
cleanliness. The OpenInterpreter-specific layer only defines `interpreter exec`
command construction, Codex-like JSONL usage parsing and containment preflight.

OpenInterpreter can execute code, so live promotion is fail-closed unless these
preconditions pass:

- `interpreter doctor --json` returns overall OK for the selected model.
- The model binding is explicit.
- The selected provider's credential source is available to the `interpreter`
  process. For custom providers the variable name comes from OpenInterpreter's
  provider `env_key`; ALK can pass a private env file only when the operator
  explicitly allows that variable with `--host-env-allow`.
- Live runs use `interpreter --ask-for-approval never --no-alt-screen exec
  --json --ephemeral --sandbox read-only`.
- Web search is not enabled.
- A clean dedicated worktree is clean before and after each invocation.

Current local evidence for `interpreter` 0.0.34 passed preflight, containment,
live conformance, live host conformance, live calibration and lifecycle final
proof. Redacted
summary evidence is stored in
`docs/adapters/evidence/openinterpreter-live-verified.md`; raw `work/`
artifacts remain host-local and ignored.

## Planning-only launch status

Exact-version profile: `0.0.34`. Profile status: `UNSUPPORTED`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The installed command surface does not expose a reliable native read-only profile.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter openinterpreter --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/openinterpreter.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/openinterpreter.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/openinterpreter.json
```

A successful version preflight does not authorize planning launch.
`managedLaunch.status` remains `WRAPPER_ONLY`, and adapter maturity cannot
promote planning support. See [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with OpenInterpreter

The bundled OpenInterpreter projection does not install an ALK plugin or skill
inside the host. Use the command route, or a separately reviewed host-local
wrapper:

Inside-session ALK use is not shipped for this adapter, so there is no bundled
in-session prompt example.

```bash
agent-lifecycle start --adapter openinterpreter --file task.md
```

The command does not start OpenInterpreter by default. See [Using ALK with an
adapter](usage-modes.md).
