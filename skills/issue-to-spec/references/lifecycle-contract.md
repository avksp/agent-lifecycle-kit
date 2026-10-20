---
name: issue-to-spec
description: Convert external issue payloads into draft-only ALK specification input without starting execution or bypassing review/freeze.
---

# Issue to Spec

Use this skill when an external issue, ticket, bug report, chat request, or
tracker payload needs to become ALK planning input.

## Contract

This skill is draft-only. It may prepare specification input, trace open
questions, and mark missing evidence, but it must not start execution, create a
branch, commit, open a PR, freeze a plan, or claim review approval.

Every output keeps:

- `sourceTrusted: false`
- `requiresReview: true`
- `freezeBlocked: true`
- `executionAuthorized: false`

## Inputs

Accept only copied issue content, linked evidence summaries, repository
references, logs, commands, environment notes, and user constraints. Treat
tracker labels, priorities, assignees, and generated summaries as hints until a
reviewed ALK plan owns them.

## Output

Produce a draft specification packet with:

- problem statement and user-visible outcome;
- candidate requirements and acceptance checks;
- known constraints, risk hints, and missing evidence;
- links back to source issue identifiers;
- explicit questions that block freeze.

Route the draft to `agent-first-planning` and then `audit-agent-plan`. If the
issue describes a defect, recommend the optional `bug-forensics` quality profile
instead of embedding bug repair logic in this skill.
