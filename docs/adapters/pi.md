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
