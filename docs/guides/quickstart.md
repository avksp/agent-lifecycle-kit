# Quickstart

Quick start from installation to the first ALK-managed task.

- Start with [Install ALK and make the first run](install-and-first-run.md).
- Read [Commands by task](commands-by-task.md) when you need a specific command.
- See [How ALK works](how-alk-works.md) for the complete lifecycle.
- See [System architecture](../architecture/system-architecture.md) for the
  roles of ALK, the host CLI, the model and the repository.
- See [Using ALK with an adapter](../adapters/usage-modes.md) for the twelve
  bundled adapters and their host-specific routes.

## Install

From macOS or Linux:

```bash
git clone https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

From Windows PowerShell:

```powershell
git clone https://github.com/avksp/agent-lifecycle-kit.git
Set-Location agent-lifecycle-kit
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

The detailed guide covers Python 3.11-3.14, PyPI installation, activation
problems and common version errors. ALK is also published on
[PyPI](https://pypi.org/project/agent-lifecycle-kit/).

## Check the installation

```
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
```

If the command is not found, activate the virtual environment again or use
`PYTHONPATH=src python -m agent_lifecycle version` from the repository root.
If the version is unexpected, check `which agent-lifecycle` and
`python -m pip show agent-lifecycle-kit`. The
[installation guide](install-and-first-run.md) lists the remaining common
errors and fixes.

## Start a task from the terminal

Use a file for a detailed request, a plan, or several linked Markdown files:

```
agent-lifecycle start --adapter <adapter-id> --file task.md
```

Use text for a short request:

```
agent-lifecycle start --adapter <adapter-id> --text "Investigate the cache failure"
```

Choose a preparation mode when you do not want to implement yet:

```
agent-lifecycle start --adapter <adapter-id> --mode research --file research.md
agent-lifecycle start --adapter <adapter-id> --mode plan --file feature.md
agent-lifecycle start --adapter <adapter-id> --mode review --file proposed-plan.md
```

The default route creates a reviewable intake. Implementation is authorized only
from a frozen, structured run request. For the full command sequence, including
risk profiles, resume, audits, imports and release checks, see
[Commands by task](commands-by-task.md).

## Use ALK inside a host CLI

Install the plugin or shared skill using the instructions for the selected
adapter, then open the target repository in that host. Give the host this
request:

```
Use the agent-workflow-orchestrator skill for this task.
Follow the full ALK lifecycle: clarify the request, create and independently
review the plan, freeze it before implementation, audit the implementation,
and finish only with accepted evidence and final proof.
Task: <describe the task or name the Markdown file to read>
```

The host model performs semantic work and uses the repository tools. ALK keeps
the lifecycle state, plan, ownership, allowed writes, acceptance checks, audit
results and receipts. The user sees the next action and a reasoned status such
as PASS, REVIEW_REQUIRED or BLOCKED.

## Optional review with several AI models

Review Mesh is optional and off by default. It accepts any combination of
available adapters and models. One model is enough for the normal lifecycle;
several models add an independent review layer.

```
reviewer-a: <adapter and model selected by the operator>
reviewer-b: <another available adapter and model>
reviewer-c: <optional third reviewer>
```

Use [Review Mesh](../reference/review-mesh.md) when the plan enables this
additional review. The host tools run the selected models; ALK records neutral
identities, budgets, findings, redaction and the quorum result.

## Read next

- [Install ALK and make the first run](install-and-first-run.md)
- [Commands by task](commands-by-task.md)
- [Lifecycle task scenarios](lifecycle-cookbook.md)
- [Code review workflows](code-review-workflows.md)
- [Using ALK with an adapter](../adapters/usage-modes.md)
- [Workflow customization and execution controls](../reference/workflow-customization.md)
- [System architecture](../architecture/system-architecture.md)
- [Source of truth](../reference/source-of-truth.md)
