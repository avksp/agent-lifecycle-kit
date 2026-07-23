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

## Commit message convention

Use a small Conventional Commits subset:

```text
<type>(optional-scope): <short imperative summary>
```

Allowed types:

- `feat:` — new user-facing capability.
- `fix:` — behavior, contract, or compatibility fix.
- `docs:` — documentation-only change.
- `test:` — test-only change.
- `chore(release):` — release, version, packaging, or publishing work.

Examples:

```text
feat(context): add small-context profile renderer
fix(workflow): reject stale gate receipts
docs(readme): document marketplace installation
test(adapters): cover publication manifests
chore(release): prepare v0.1.2 marketplace publication
```

Rules:

- Keep the subject short, ideally 72 characters or less.
- Use English commit messages.
- Do not mix unrelated changes in one commit.
- Use `chore(release): prepare vX.Y.Z ...` for version bumps, release manifests, tags, marketplace metadata, and release docs.
- Breaking changes must be explicit with `!` or a `BREAKING CHANGE:` body.

Before opening a change, run:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```
