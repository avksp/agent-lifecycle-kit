# Plugin publication

ALK publication uses immutable semantic-version tags as the primary install
path. A repository tag is not enough: the installable plugin metadata inside
the tag must also declare the same version and source ref.

## Contract

`agent-publication-manifest.v1` lists the package, plugin and marketplace
surfaces that must move together:

- package version files: `pyproject.toml`, `uv.lock`,
  `src/agent_lifecycle/_version.py`;
- root plugin manifests for Codex, Claude Code and Cursor;
- adapter-local plugin projections for Codex, Claude Code and Cursor;
- marketplace manifests and their tagged source refs.

Plugin manifests use `version: X.Y.Z`. Marketplace entries that install from a
repository tag use `source.ref: vX.Y.Z`. Marketplace files may also carry a
display `version`, but that value must remain the same semver.

## Validation

Before a release tag is accepted, run:

```bash
python tools/release/validate_publication_versions.py \
  --target-version X.Y.Z \
  --target-ref vX.Y.Z \
  --evidence work/<release>/evidence/publication-versions.json
```

The validator fails when any tracked publication surface is stale or uses the
wrong field form. It emits `agent-publication-version-validation.v1` and does
not claim production promotion or public marketplace approval.

## Floating channel

A mutable `last` value is not allowed in `plugin.json.version`. If a host
supports a floating channel, it may only be an opt-in source ref that points at
an already accepted release commit. The installed plugin must still declare the
real semver version. If a host cannot keep those two concepts separate, ALK
uses semver-only installation for that host.
