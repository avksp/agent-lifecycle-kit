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
- Plan packages, locks, reviews, task results and workflow state are local
  lifecycle artifacts. Keep them under ignored `work/`, `tasks/` or `.alk/`
  paths; never add files under repository-root `plans/` to Git.

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
chore(release): prepare v0.2.0 marketplace publication
```

Rules:

- Keep the subject short, ideally 72 characters or less.
- Use English commit messages.
- Do not mix unrelated changes in one commit.
- Use `chore(release): prepare vX.Y.Z ...` for version bumps, release manifests, tags, marketplace metadata, and release docs.
- Breaking changes must be explicit with `!` or a `BREAKING CHANGE:` body.

## Python quality checks

The runtime package keeps zero dependencies. Development quality tools are
isolated in the `quality` dependency group and pinned by `uv.lock`:

```bash
uv sync --locked --group quality
uv run --frozen --group quality ruff check src/agent_lifecycle
uv run --frozen --group quality ruff format --check src/agent_lifecycle
uv run --frozen --group quality mypy src/agent_lifecycle
```

The release quality runner records bounded Ruff, format, mypy and coverage
evidence. A baseline is a review-bound migration aid: it cannot grow, its
source digest cannot drift, and a file being changed must leave its baseline.
Do not suppress a finding or edit a baseline to make a change pass without a
reviewed owner, reason and source update.

Before opening a change, run:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m agent_lifecycle.neutrality scan --scope current-tree-complete --policy policy/neutrality.policy.json --require-zero-findings
```

The release-security suite rejects any tracked `plans/**` path. Reusable
configuration belongs under `profiles/`; deterministic test-only inputs belong
under `tests/fixtures/`.
