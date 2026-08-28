# Install ALK and make the first run

Use the source checkout when you want to inspect or contribute to ALK. Use PyPI
when you only need the installed command.

## Before you start

You need:

- Git;
- Python 3.11, 3.12, 3.13 or 3.14;
- one supported host CLI if you want a model to work inside its own session.

ALK is a Python package. The `agent-lifecycle` command is installed into the
active Python environment, so activating that environment is part of the
installation.

## Install from a GitHub checkout

### macOS and Linux

```bash
git clone https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m agent_lifecycle version
agent-lifecycle version
```

Keep the terminal with `.venv` active while using the checkout. To activate it
again later:

```bash
cd agent-lifecycle-kit
source .venv/bin/activate
```

### Windows PowerShell

```powershell
git clone https://github.com/avksp/agent-lifecycle-kit.git
Set-Location agent-lifecycle-kit
py --version
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m agent_lifecycle version
agent-lifecycle version
```

If PowerShell blocks activation for this terminal, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

To activate the environment again later:

```powershell
Set-Location agent-lifecycle-kit
.\.venv\Scripts\Activate.ps1
```

## Install the published package

Use an isolated environment for a package installation as well.

### macOS and Linux

```bash
python3 -m venv ~/.venvs/alk
source ~/.venvs/alk/bin/activate
python -m pip install --upgrade pip
python -m pip install agent-lifecycle-kit==2.7.0
python -m agent_lifecycle version
agent-lifecycle version
```

### Windows PowerShell

```powershell
py -m venv "$HOME\venvs\alk"
& "$HOME\venvs\alk\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install agent-lifecycle-kit==2.7.0
python -m agent_lifecycle version
agent-lifecycle version
```

The [PyPI package](https://pypi.org/project/agent-lifecycle-kit/) supports
Python 3.11-3.14. An exact version keeps the command, plugin metadata and
documentation on the same release.

## Check the installation

Run these commands from the project where you want to work:

```bash
python -m agent_lifecycle version
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
```

The first command prints the installed version. The second writes a redacted
readiness report and checks package metadata, profiles, adapter descriptors and
available local evidence.

## If `agent-lifecycle version` fails

Start with the form that does not depend on the console script:

```bash
python -m agent_lifecycle version
```

Then match the message to the remedy:

| Message | Remedy |
| --- | --- |
| `command not found` or `is not recognized` | Activate `.venv`, then run `python -m pip install -e .` again. The command is installed inside the active environment. |
| `No module named agent_lifecycle` | Change to the checkout and install it, or run `PYTHONPATH=src python -m agent_lifecycle version` from the checkout. |
| `dataclass() got an unexpected keyword argument 'slots'` | The interpreter is too old. Use Python 3.11-3.14, recreate the environment and reinstall. |
| The printed version is unexpected | Run `python -c "import sys; print(sys.executable)"` and `python -m pip show agent-lifecycle-kit`; another Python environment is active. |

For a source checkout, the direct fallback is:

```bash
cd agent-lifecycle-kit
PYTHONPATH=src python -m agent_lifecycle version
.venv/bin/agent-lifecycle version
```

PowerShell:

```powershell
Set-Location agent-lifecycle-kit
$env:PYTHONPATH = "src"
python -m agent_lifecycle version
.venv\Scripts\agent-lifecycle.exe version
```

## Make the first ALK request

There are two entrypoints:

1. The terminal command creates a bounded ALK intake receipt from text or a
   Markdown file.
2. A host plugin or skill lets Codex, Claude Code, OpenCode and other supported
   hosts use the same lifecycle inside their session.

Terminal route:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --text "Investigate the cache failure and prepare a reviewed plan"
```

Or provide a file:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --file task.md
```

Raw text and Markdown enter the review-gated draft stage. The command records
the request; it does not turn an unreviewed request into implementation
authority. Choose the adapter id from the [adapter support
matrix](../adapters/support-matrix.md).

## Install a host plugin or skill

Choose one host and follow its adapter page. The common sequence is:

1. install the tagged plugin or expose the tagged skill;
2. restart the host, or reload its plugins;
3. open the target project;
4. explicitly request the ALK workflow in the prompt;
5. check the generated plan and receipts before allowing implementation.

Codex:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref v2.7.0
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
codex plugin list
```

Restart Codex after installation. Claude Code:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
claude plugin list
```

Run `/reload-plugins` in the active Claude Code session. OpenCode loads skills
and its JavaScript projection separately; use the [OpenCode adapter
page](../adapters/opencode.md) for the project-level copy commands. The
[adapter installation guide](../adapters/install.md) contains the corresponding
routes for all bundled adapters.

After installation, verify package discovery with the [Agent Plugins client
qualification](../reference/agent-plugin-qualification.md) command. It is an
explicit read-only check and does not replace the ALK lifecycle.

Release 2.0 makes workflow the only lifecycle authority. Historical runner
records use the [2.x migration guide](runner-migration-2.md) and remain
read-only, non-authoritative evidence.

Release 2.4 adds an optional [security analysis profile](../reference/security-analysis-profile.md).
It is disabled by default; imported findings are read-only evidence and a
high-severity remediation needs independent verification at task acceptance.

Release 2.5 adds optional [bounded external tool jobs](../reference/external-tool-jobs.md)
for adapter-owned work that needs cancellation, child cleanup or hashed
artifacts. Ordinary workflows do not allocate job state, and the feature adds
no provider client or second lifecycle authority.

Release 2.6 adds [release accounting](../reference/release-accounting.md) and a
bounded [phase-to-session handoff](phase-session-handoff.md). Missing telemetry
stays unavailable, and handoff artifacts do not replace workflow authority.
Before execution, create a reviewed final lock with
`agent-lifecycle plan lock-create --manifest <path> --review <path>`; it fails
rather than replacing an existing `plan.lock.json`. See the [CLI
reference](../reference/cli.md).

Release 1.80 also documents optional lifecycle control inside an adapter. It is
off by default: bundled adapters currently publish `GUIDANCE_ONLY` and
`NO_RECOMMENDATION`, while managed launch remains `WRAPPER_ONLY`. See
[optional adapter lifecycle control](../adapters/lifecycle-control.md) for the
operation levels, event boundaries and exact-version qualification rules.

## Use the plugin in the host prompt

After restarting or reloading the host, send a request like this:

```text
Use the agent-workflow-orchestrator skill for this task.
First clarify the request and produce a reviewed ALK plan.
Do not implement until the plan is reviewed and frozen.
After implementation, run the required audits and finish only with accepted
evidence and final proof.
Task: read task.md and investigate the cache failure.
```

The host model performs clarification, analysis and code work. ALK keeps the
plan, state, ownership, checks, reviews and accepted receipts connected. A
successful natural-language answer is not the completion signal; the visible
result is a structured status such as `PASS`, `REVIEW_REQUIRED` or `BLOCKED`
with the related artifact and reason.

## Continue from here

- [Quickstart](quickstart.md) is the short path for the next session.
- [Commands by task](commands-by-task.md) contains the complete command map.
- [Using ALK with an adapter](../adapters/usage-modes.md) explains host and
  terminal routes.
- [Workflow customization](../reference/workflow-customization.md) explains
  stages, models, prompts, timeouts, retries and multi-agent review.
- [System architecture](../architecture/system-architecture.md) explains the
  roles of ALK, the host, the model and the repository.
- [Plan verification and integrity](../reference/plan-verification.md) explains
  how a reviewer checks a handed-off plan package before implementation.
