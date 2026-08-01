# Issue to specification drafts

External issues are useful intake, not execution authority. The
`issue-to-spec` skill converts a ticket, bug report, chat request, or tracker
payload into draft ALK planning input.

The output must stay draft-only:

- `sourceTrusted: false`
- `requiresReview: true`
- `freezeBlocked: true`
- `executionAuthorized: false`

The draft should preserve source issue ids, candidate requirements, acceptance
checks, constraints, risk hints, missing evidence, and questions that block
freeze. It then routes through `agent-first-planning` and `audit-agent-plan`.

For defect reports, the draft can recommend the optional Bug Forensics profile,
but reproduction and repair evidence still belong to the reviewed plan.
