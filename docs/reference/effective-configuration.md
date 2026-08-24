# Effective configuration explanation

Release 1.87 adds one read-only command for explaining the configuration that
will govern an ALK operation:

```bash
agent-lifecycle project profile explain \
  --profile .alk/project-profile.json \
  --preset feature-implementation \
  --manifest tasks/release-1-87/plan.manifest.json \
  --lock tasks/release-1-87/plan.lock.json \
  --descriptor adapters/claude/adapter.descriptor.json \
  --capability-manifest adapters/claude/capabilities.manifest.json
```

The command reads explicit, project-contained inputs and returns
`agent-effective-configuration-explanation.v1`. It does not launch a host,
call a model or modify a profile, plan or lock.

## Source precedence

The precedence is field-specific and is reported for every effective field:

1. built-in defaults seed an unset value;
2. a built-in preset supplies defaults below an explicit project profile;
3. an explicit project profile replaces the preset for fields it owns;
4. bounded command overrides replace only allowed profile fields;
5. frozen-plan authority is a constraint, not a generic last-write-wins source.

The result reports `winningSource`, `overriddenSources` and `planConstraint`.
For risk, the plan is a minimum floor. A tighter command value is accepted, but
a downgrade returns `risk-tier-downgrade`. A required review mesh or a
non-widening thread-bridge policy cannot be disabled by a profile or command.

Adapter capability never selects a value. After descriptor and capability
lineage validation, it only reports whether the selected field is
`GUIDANCE_ONLY`, `OBSERVED`, `ENFORCED` or `UNAVAILABLE`.

## Fail-closed lineage

The descriptor and capability manifest are checked against each other before
enforceability is attributed. Missing, invalid or stale descriptor/capability
evidence returns `UNAVAILABLE` and `status: FAIL` while retaining the selected
configuration value for diagnosis. It cannot promote a field or weaken a plan
constraint.

The output contains digests and stable blocker codes rather than raw host
content, prompts, model reasoning, credentials or local absolute paths.

See [adapter action evidence](adapter-action-evidence.md), [project workflow
profile](project-workflow-profile.md) and [optional adapter lifecycle
control](../adapters/lifecycle-control.md).
