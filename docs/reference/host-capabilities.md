# Host Capabilities

Host capabilities describe what a host adapter can expose to ALK without using
host or provider identity as a shortcut for behavior.

`agent-host-capability.v1` is an additive declaration carried by adapter
descriptors and capability manifests. The first capability is `acp`, with these
rules:

- `support` is one of `supported`, `unsupported` or `unknown`.
- `providerIdentityUsed` is always `false`.
- `supported` requires `transport: "acp"`, `evidencePolicy:
  "probe-required"` and an invocation contract using
  `agent-host-operation-request.v1` plus `agent-host-operation-receipt.v1`.
- Host probes are safe preflight checks only. They must not start live model
  calls and are recorded with `agent-acp-probe-receipt.v1`.
- Missing executable, failed probe or invalid invocation contract is a blocking
  failure for a `supported` declaration.

Hosts without probe evidence should be represented as `unsupported` or
`unknown`, or omitted from the positive capability evidence set.

## Adapter package discovery

`tools/release/discover_adapter_packages.py` scans adapter package directories
for `adapter.descriptor.json` and `capabilities.manifest.json`. The output is
advisory only:

- descriptors remain authoritative for the adapter support level;
- capability manifests remain authoritative for supported operations;
- discovery cannot promote adapters or override descriptor claims;
- no host command or model call is started.

Use discovery to inspect source packages before release assembly, not to make
runtime decisions.
