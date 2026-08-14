# Agent Plugins client qualification

[Русская версия](../ru/reference/agent-plugin-qualification.md)

ALK publishes a portable Agent Plugins package with the seven maintained
lifecycle skills. Client qualification answers a narrower question: whether a
selected client can discover the package that the operator installed.

## What is checked

The qualification receipt is bound to:

- the exact package version and package digest;
- the selected client profile and its digest;
- the observed client version;
- the `plugin.json` projection and seven canonical skills; and
- the result of two read-only client commands, when a live probe is run.

The client owns installation, trust prompts, permissions, updates and local
caches. ALK does not install a plugin or change client configuration.

## Offline verification

Build and inspect the package without starting a client:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 tools/release/build_agent_plugin.py \
  --root . \
  --version 1.68.0 \
  --out work/release-1-68/agent-plugin \
  --archive work/release-1-68/agent-lifecycle-kit-agent-plugin-v1.68.0.zip

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 \
  tools/release/validate_agent_plugin_qualification.py \
  --package work/release-1-68/agent-plugin \
  --profile adapters/codex/agent_plugin_profile.json \
  --version 1.68.0 \
  --evidence work/release-1-68/evidence/offline.json
```

This mode starts zero host processes and makes zero model or network calls.
The result is `OFFLINE_VALIDATED` when the package and profile match.

## Qualification after installation

Install the package through the selected client's own procedure. Then run the
ALK probe with the profile for that client:

```bash
agent-lifecycle adapter plugin-qualify \
  --adapter codex \
  --profile adapters/codex/agent_plugin_profile.json \
  --package work/release-1-68/agent-plugin \
  --project-root . \
  --out work/release-1-68/evidence/codex-qualification.json
```

The probe executes only the profile's version and help commands, with
`shell=False`, an exact environment allowlist, a ten-second command limit and a
bounded output limit. The receipt stores hashes, counts, versions and statuses;
it does not store prompts, raw host output, secrets or absolute paths.

The result is one of:

- `QUALIFIED` — the package and client projection were found and both
  read-only commands passed;
- `OFFLINE_VALIDATED` — only the package was checked;
- `BLOCKED` — package, projection or version evidence did not satisfy the
  profile; or
- `UNAVAILABLE` — the selected client executable was not available.

A qualification receipt is evidence for the named client and profile only. It
does not prove ALK lifecycle execution, a reviewed plan, managed native launch
or adapter promotion. Those claims still require the corresponding ALK
artifacts and gates.

## Profiles

The release ships data-only profiles for:

- [Codex](../../adapters/codex/agent_plugin_profile.json)
- [Claude Code](../../adapters/claude/agent_plugin_profile.json)
- [Cursor](../../adapters/cursor/agent_plugin_profile.json)

Validate all profiles before use:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 \
  tools/release/validate_agent_plugin_profiles.py \
  --profiles adapters/codex/agent_plugin_profile.json \
             adapters/claude/agent_plugin_profile.json \
             adapters/cursor/agent_plugin_profile.json \
  --evidence work/release-1-68/evidence/profiles.json
```

The profiles cannot change adapter maturity or `managedLaunch.status`.
Each profile also declares a host-version policy. The shipped profiles use
`mode: reported` with `accepted: any-version`: the observed client version is
recorded in the receipt, while the profile does not turn that observation into
an open-ended support or lifecycle claim.

The qualification profile and receipt are versioned local contracts validated
by the qualification commands. They are intentionally kept separate from the
global lifecycle schema catalogue.
Release 1.68 uses the observation-only policy for its shipped profiles; a
closed version range requires a separately implemented and validated policy.
