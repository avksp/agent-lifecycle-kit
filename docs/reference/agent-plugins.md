# Portable Agent Plugins package

ALK publishes its maintained skills as a portable package for clients that
implement the [Agent Plugins specification](https://agent-plugins.org/specification).
The package is an additional delivery format for ALK skills. It does not
replace the Python package, adapter projections or lifecycle commands.

## Package contents

The release archive contains one root manifest and the canonical ALK skills:

```text
agent-lifecycle-kit-agent-plugin-v2.29.0.zip
├── plugin.json
├── docs/
│   ├── guides/
│   ├── reference/
│   └── ru/
└── skills/
    ├── agent-first-planning/SKILL.md
    ├── agent-plan-to-workers/SKILL.md
    ├── agent-workflow-orchestrator/SKILL.md
    ├── audit-agent-plan/SKILL.md
    ├── audit-plan-implementation/SKILL.md
    ├── bug-forensics/SKILL.md
    └── issue-to-spec/SKILL.md
```

The root manifest uses the Agent Plugins 1.0.0 contract and declares the
release version. The `skills/` directory is generated from the repository
`skills/` tree, which remains its only content source.


The bounded `docs/` projection contains 19 required EN/RU guides and references.
The exact allowlist is `REQUIRED_DOCUMENTS` in `tools/release/agent_plugin_package.py`;
repository documents remain the only authoring source. Links from skills resolve
relative to the skill root inside this package, never against consumer-project
files. Missing or changed required documents fail source/package/ZIP parity.
The optional Russian Review Mesh translation is not bundled. Package availability
is not proof of host installation or lifecycle enforcement. The 512 KiB per-skill
and 4 MiB total package/archive bounds remain unchanged.

## Install through a compatible client

This resource layout starts with 2.29.0. The examples below name that release.
Until it is published, build from the candidate source instead of downloading
an older archive: 2.28.0 contains skills but not this required documentation.

Download the archive from the [GitHub release](https://github.com/avksp/agent-lifecycle-kit/releases/tag/v2.29.0), unpack it and follow the installation procedure of the selected client. The specification defines the package and component layout; the client defines the installation command, trust prompt, permissions, updates and local cache.

For client-specific commands, use the [adapter installation guide](../adapters/install.md) and the page for the selected adapter. The package can also be inspected locally before installation:

```bash
python tools/release/build_agent_plugin.py \
  --root . \
  --version 2.29.0 \
  --out work/agent-plugin \
  --archive work/agent-lifecycle-kit-agent-plugin-v2.29.0.zip

python tools/release/validate_agent_plugin.py \
  --package work/agent-plugin \
  --archive work/agent-lifecycle-kit-agent-plugin-v2.29.0.zip \
  --root . \
  --version 2.29.0 \
  --evidence work/agent-plugin-validation.json
```

The validator checks the local schema digest, manifest identity, skill
discovery, regular files, containment and archive paths without network or
model calls.

After the client-owned installation step, use the [Agent Plugins client
qualification](agent-plugin-qualification.md) page to run the explicit
read-only probe for Codex, Claude Code or Cursor. The resulting receipt binds
the package to the selected client; it does not replace lifecycle proof.

## Package loading and lifecycle proof

After a compatible client loads the package, the ALK skills become available
to that client. Loading a skill does not by itself create a specification,
freeze a plan, authorize file changes or produce an accepted implementation
audit. The host must still run the ALK lifecycle and retain its artifacts:

1. clarify the request and create the specification;
2. review and freeze the plan and lock;
3. execute only the authorized task packets;
4. record validation and evidence receipts;
5. accept the implementation and produce final proof.

The [source-of-truth guide](source-of-truth.md) explains which artifacts carry
authority. The [plugin publication contract](plugin-publication.md) explains
versioned release surfaces and update rules.

## Boundaries

- The package contains skills and required static documentation only. It does not contain ALK source code,
  runtime state, project tasks, secrets, adapter credentials or `mcp.json`.
- The package does not start a host CLI or a model. Host execution remains an
  explicit adapter and local-profile concern.
- The generated archive is a release projection. Do not edit it by hand; use
  the repository `skills/` and `docs/` sources and rebuild it for a new release.
- The package version is immutable semver. Client-specific plugin manifests
  and marketplace projections remain separate publication surfaces.

Русская версия: [Переносимый пакет Agent Plugins](../ru/reference/agent-plugins.md).
