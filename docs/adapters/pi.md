# Pi Adapter

The Pi projection is host-specific `VERIFIED` for Pi `0.83.0` on the tested
host-local provider/model binding. It uses RPC/JSON plus AGENTS/agentskills
metadata. Its descriptor records the alternate protocol surface as unsupported
by default and keeps all lifecycle semantics delegated to ALK core.

Tracked source artifacts:

- `adapters/pi/adapter.descriptor.json`
- `adapters/pi/capabilities.manifest.json`
- `conformance/adapters/pi/offline-baseline.json`
- `tools/live_hosts/pi_harness.py`
- `docs/adapters/evidence/pi-live-verified.md`

The verified claim is limited to the tested Pi `0.83.0` host range and does not
claim public package approval, does not claim public directory approval,
production promotion or ACP support. Live promotion used bounded
no-session/no-tools/no-context invocations with explicit provider/model
selection, redacted host-env handling, clean-worktree checks, live conformance,
live calibration and accepted lifecycle proof.

For local reruns, the selected Pi provider remains responsible for the
credential name and source. ALK only scopes an operator-approved env file into
the harness process:

```bash
python tools/live_hosts/pi_harness.py \
  --mode preflight \
  --pi-provider <provider> \
  --pi-model <model-id> \
  --host-env-file ~/.config/alk/hosts/pi.env \
  --host-env-allow <PROVIDER_API_KEY_NAME> \
  --budget-mode subscription \
  --max-invocations 14 \
  --max-billable-tokens <token-cap> \
  --allow-live \
  --report work/<release>/evidence/preflight/pi-preflight-report.json
```

Replace `<PROVIDER_API_KEY_NAME>` with the env-key name required by the
selected provider. The value must stay outside tracked repository files and
receipts.

## Planning-only launch status

Exact-version profile: `0.83.0`. Profile status: `UNSUPPORTED`. Planning
support: `PLANNING_ONLY_UNSUPPORTED`. The read-only tool list exists, but bounded stdin result transport has not been verified.

Generate and inspect the local profile with:

```bash
agent-lifecycle adapter launch-profile --adapter pi --repository-root /path/to/agent-lifecycle-kit --out .alk/host-launch/pi.json
agent-lifecycle host-launch inspect --profile .alk/host-launch/pi.json
agent-lifecycle host-launch preflight --profile .alk/host-launch/pi.json
```

A successful version preflight does not authorize planning launch.
`managedLaunch.status` remains `WRAPPER_ONLY`, and adapter maturity cannot
promote planning support. See [Planning-only adapter
launch](../reference/planning-only-launch.md).

## Use ALK with Pi

Expose the tagged `agent-workflow-orchestrator` skill through Pi's native
AGENTS/Agent Skills configuration and request it for the task. The bundled
projection does not modify that host configuration automatically.

```text
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle through reviewed planning, plan freeze,
implementation audits and accepted final proof.
Task: <describe the task or name the Markdown file to read>
```

The request above applies only after that host-local skill configuration.

The command route is always explicit:

```bash
agent-lifecycle start --adapter pi --file task.md
```

It creates ALK intake and does not start Pi by default. See [Using ALK with an
adapter](usage-modes.md).
