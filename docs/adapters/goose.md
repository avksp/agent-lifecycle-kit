# Goose Adapter

The Goose adapter is an EXPERIMENTAL ALK adapter projection for hosts that
provide an ACP-compatible command surface.

## Files

- Descriptor: `adapters/goose/adapter.descriptor.json`
- Capability manifest: `adapters/goose/capabilities.manifest.json`
- Offline tests: `tests/adapters/goose/test_goose_adapter.py`
- Probe receipt tests: `tests/live_hosts/test_goose_adapter.py`

## Capability Contract

The descriptor declares `hostCapabilities[0].capabilityId = "acp"`. This is a
neutral capability claim, not a provider or model identity. Lifecycle semantics
remain delegated to ALK core, and unsupported operations use the shared
fail-closed policy.

The adapter is not marked `VERIFIED`. Promotion requires live host conformance
and calibration evidence in a later release gate.

## Validation

```bash
PYTHONPATH=src python3 -m agent_lifecycle adapter validate --descriptor adapters/goose/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json
PYTHONPATH=src python3 -m pytest tests/adapters/goose tests/live_hosts/test_goose_adapter.py
```
