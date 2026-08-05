# Optional Cross-Check Profile

The generic cross-check profile lets a plan request an additional reviewer for
high-risk work without making multi-model review part of the default lifecycle.

`agent-cross-check-profile.v1` is always:

- `OPTIONAL`;
- disabled by default;
- opt-in only;
- advisory by default;
- blocking only when the plan explicitly opts in;
- capped in tokens, invocations and wall-clock resources;
- not a canonical USD-cost surface.

## Receipts

`agent-cross-check-receipt.v1` records the subject, reviewer, findings,
independence evidence, budget cap and budget usage. Validation recomputes the
receipt digest and fails when:

- the profile digest does not match;
- usage exceeds the configured cap;
- a blocking cross-check is claimed without plan opt-in;
- independence is required but cannot be proven from neutral identity hashes;
- live calls are claimed when the profile does not allow them;
- monetary budget fields are used.

Independence is provider-neutral. The receipt compares only neutral identity
hash fields such as `hostIdentityHash` and `modelIdentityHash`; provider names,
model names and account names are not canonical contract fields.

This makes cross-check useful for S2, security, release and bug-fix tasks while
keeping ordinary work on the normal lifecycle path.

## Review Mesh relationship

Review Mesh reuses this profile for budget and independence semantics. It adds
lifecycle mode ids and assignment/result/synthesis/quorum receipts for
multi-reviewer workflows, but it does not create a separate budget model or a
second way to prove reviewer independence.
