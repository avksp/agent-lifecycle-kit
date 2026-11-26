# Compatibility and release channels

The wheel includes a candidate stable inventory at
`agent_lifecycle/data/profiles/compatibility/stable-surface.v1.json` in the
installed wheel. It lists the covered CLI commands, flags, schema IDs, exit
codes and public Python exports. CLI help marks Preview commands.

The stable policy start date, cadence and deprecation period remain open.
The release generates the [tested versions table](../reference/compatibility-tested-versions.json)
from replaying retained cases on two installed release versions. Each row
covers the listed cases and versions. Use the actual fixture and receipt
identities for production qualification.

Use the existing [update check and exact pins](../reference/plugin-updates.md).
Set an explicit version and channel to select a prerelease. Read the
compatibility result for each intended upgrade before changing a pin.

For workflow integrations, see [External AI SDLC integration](ai-sdlc-integration.md).
