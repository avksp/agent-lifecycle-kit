# Contributing

Agent Lifecycle Kit keeps lifecycle semantics in the Python core and keeps host
adapters thin. Changes should preserve these boundaries:

- Core contracts must stay provider-neutral and project-neutral.
- Native adapters may translate host invocation, discovery, approval and
  operation surfaces, but must not reimplement lifecycle decisions.
- New lifecycle behavior needs deterministic tests under `tests/`.
- New adapter claims need conformance evidence before the support matrix can
  move beyond `EXPERIMENTAL`.
- Release-candidate scripts must remain local and reproducible; production
  promotion requires separate external authority receipts.

Before opening a change, run:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```
