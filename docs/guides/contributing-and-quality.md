# Python quality and contribution checks

Release 1.77 makes the existing Python engineering discipline reproducible.
Quality tools are development-only and do not become runtime dependencies of
ALK.

## Prepare the environment

Use the locked development group before running the checks:

```bash
uv sync --locked --group quality
```

The group pins Ruff, mypy and coverage. The package itself keeps its zero
runtime-dependency contract.

## Run the local checks

Run the focused tools and the canonical test inventory:

```bash
uv run --frozen --group quality ruff check src/agent_lifecycle
uv run --frozen --group quality ruff format --check src/agent_lifecycle
uv run --frozen --group quality mypy src/agent_lifecycle
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -t . -q
```

The release evidence producer runs the same pinned tools with bounded
processes, output and wall time:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --frozen --group quality \
  python3 tools/release/run_python_quality.py \
  --policy policy/python-quality.json \
  --package-root src/agent_lifecycle \
  --tests-root tests \
  --test-top-level . \
  --base-sha <base-commit> \
  --work-root work/quality-raw \
  --evidence work/python-quality-run.json
```

Validate the generated evidence with
`tools/release/validate_python_quality.py`. The check covers correctness lint,
formatting, migration findings, line length, mypy, complete unittest
discovery and coverage.

## How the ratchet works

The policy stores path-, rule- and source-digest-bound legacy findings. A
baseline is not permission to add another finding: a new finding, a count
increase or a changed source digest blocks validation. Every file changed by a
release must leave the correctness findings behind. The 76% statement-line
coverage floor and the exact environment-bound predecessor baseline cannot be
lowered to make a release pass.

Do not disable a security, architecture or quality gate to accommodate a
change. Fix the finding, update the reviewed plan and evidence, or stop at
`REVIEW_REQUIRED`.

## Stable CLI failures and installed resources

The root CLI returns `agent-lifecycle-error.v1` with exit code `2` for expected
I/O, decoding, JSON-depth and unexpected failures. Error output is redacted and
does not contain a traceback or local absolute path. Library exceptions and
`KeyboardInterrupt`/`SystemExit` behavior remain unchanged. See the [CLI error
contract](../reference/cli-errors.md).

Built-in profiles are loaded through package resources with
`importlib.resources`, so an installed wheel works outside the source checkout
and cannot be shadowed by a same-named file in the current directory. An
explicitly supplied profile path still takes precedence. See [the Python API
boundary](../reference/python-api.md) for the supported import surface;
unlisted internal modules are not compatibility promises.

## Before opening a change

1. Keep changes inside the reviewed write set.
2. Run the focused tests for the affected behavior.
3. Run the canonical unittest discovery command and the quality checks.
4. Review JSON receipts and documentation in both supported languages.
5. Report commands, exact revisions and any remaining blockers in the change.

The release workflow remains authoritative for scope, evidence, independent
review and final acceptance.

## Single architecture policy

Numbers come from `policy/architecture-limits.json`; a test checks this table.
Targets are warnings; hard limits block validation.

| Policy key | Limit |
| --- | ---: |
| `targetFileLines` | 800 |
| `hardFileLines` | 1200 |
| `targetFunctionLines` | 80 |
| `hardFunctionLines` | 150 |
| `hardSymbols` | 80 |
| `cliTargetFunctionLines` | 80 |
| `cliHardFunctionLines` | 150 |

```bash
PYTHONPATH=src python3 tools/release/validate_architecture_complexity.py \
  --package-root src/agent_lifecycle --policy policy/architecture-limits.json \
  --evidence work/architecture-complexity.json
PYTHONPATH=src python3 tools/release/validate_module_dependencies.py \
  --package-root src/agent_lifecycle --policy policy/architecture-dependencies.json \
  --require-acyclic-modules --require-acyclic-packages \
  --evidence work/module-dependencies.json
```

The mypy baseline is empty: every new source-wide mypy error blocks acceptance.
The obsolete `runner/attempt_snapshots.py` entry is removed; deleted source is not restored.
Existing lint/format baselines do not expand and the 76% coverage floor stays fixed.
Run full local unittest once for an unchanged candidate; the CI quality runner
performs discovery for its own coverage evidence. Repeating a successful local
check requires a change to its dependencies.
