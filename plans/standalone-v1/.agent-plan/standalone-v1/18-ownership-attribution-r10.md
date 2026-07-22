# Ownership Attribution Correction r10

Revision 10 is a plan-only correction for exact write attribution discovered
during execution pre-acceptance audit.

## Change

- `plans/standalone-v1/plan.manifest.json` is controller-owned because it is the
  mutable package manifest used during refreeze.
- The Russian README is stored as `docs/guides/README.ru.md`, linked from the root
  English README, and belongs to WS-14 as part of the release documentation
  surface already covered by `docs/guides`.
- The root `tests/__init__.py` marker is removed because stdlib discovery
  already works from subpackage markers and the root marker is outside a worker
  namespace.

## Non-change

- No product requirement, SDD tier, adapter scope, controller gate, task
  dependency, or implementation acceptance criterion is widened.
- Existing workstream sequencing remains unchanged.
- This revision only closes unowned-path attribution before any task acceptance.
