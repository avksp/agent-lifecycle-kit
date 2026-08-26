# Plan review

Status: `FROZEN / FINAL REVISION 10 / PRE_IMPLEMENTATION`.

## Closed decisions

- the feature is optional and inactive by default
- existing workflow state remains the only authority
- no provider, network or external-tool runtime enters the core
- ordinary runs create no new work or artifact when the feature is unused
- activation is based on two hash-bound incident shapes from independent projects
- no-final-verdict and partial child output never count toward acceptance
- cancellation owns process-group cleanup and immutable per-attempt output isolation
- interrupted jobs are never resumed in place; recovery creates a new attempt and preserves the old namespace
- shared `process.py` and `process_groups.py` remain read-only; the job service composes their existing cancellation and cleanup contract
- terminal parents cancel every declared child; live child processes block parent success and partial child output stays diagnostic-only
- process-limit and incident-reproduction evidence is owned by WS25-02, which owns the corresponding runtime and cleanup fixtures
- private storage composes existing path and private-file helpers; host_protocol remains validation-only
- runtime dependencies remain empty and are checked deterministically

## Independent review focus

1. whether the activation case demonstrates a real lifecycle gap
2. whether existing contracts can solve it without a new surface
3. authority, privacy, replay and resource boundaries
4. negative fixtures and unavailable behavior
5. English and Russian operational parity

## Freeze conditions

- retain `activation-evidence.md` as planning authorization and produce separate exact-candidate conformance evidence;
- rebase onto the accepted Release 2.4.1 merge;
- raise `planRevision` after remediation;
- pass completeness, plan check, acceptance and refs checks;
- close every independent S2 Medium or High finding;
- generate `agent-plan-lock.v2` only for the final audited revision.
- bind the final independent `agent-plan-review.v1` as `plan-review-r10.json` before lock generation.
