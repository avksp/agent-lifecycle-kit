"""Check the reviewed stable candidate inventory against the live package."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, load_json, write_json
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.release.release_common import digest_value, load_json, write_json

from agent_lifecycle.cli.parsers import build_parser
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.schemas import get_schema

SURFACE = Path("src/agent_lifecycle/data/profiles/compatibility/stable-surface.v1.json")
PYTHON_POLICY = Path("policy/python-public-api.json")
SCHEMA = "agent-stable-surface.v1"
_VERSION = re.compile(r"\d+\.\d+\.\d+")


def _leaf(root: argparse.ArgumentParser, path: list[str]) -> argparse.ArgumentParser | None:
    current = root
    for part in path:
        family = next((item for item in current._actions if isinstance(item, argparse._SubParsersAction)), None)
        if family is None or part not in family.choices:
            return None
        current = family.choices[part]
    return current


def external_classification(guide: str) -> tuple[set[str], set[str]]:
    """Read the maintained external command and wire-schema table."""
    operations = guide.split("## Bounded operation map", 1)[1].split("\n## ", 1)[0]
    cli = set()
    schemas = set()
    for line in operations.splitlines():
        if not line.startswith("| "):
            continue
        column = line.split("|", 3)[2]
        tokens = re.findall(r"`([^`]+)`", column)
        for token in tokens:
            if token.startswith("agent-lifecycle "):
                cli.add(token.split(" --", 1)[0].removeprefix("agent-lifecycle "))
            elif re.fullmatch(r"agent-[a-z0-9-]+\.v[0-9]+", token):
                schemas.add(token)
    if not cli or not schemas:
        raise ValueError("External contract table is empty")
    return cli, schemas


def _invoke_case(root: Path, argv: list[str]) -> tuple[int, dict[str, Any]]:
    project = Path(__file__).resolve().parents[2]
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "TMPDIR", "USERPROFILE", "HOME")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["PYTHONPATH"] = str(project / "src")
    child = subprocess.run(
        [sys.executable, "-B", "-m", "agent_lifecycle", *argv],
        cwd=root,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    return child.returncode, json.loads(child.stdout)


def _observed_case(root: Path, argv: list[str], field: str, value: str) -> int:
    code, report = _invoke_case(root, argv)
    if report.get(field) != value:
        raise ValueError("Stable probe did not reach its expected command outcome")
    return code


def _workflow_cases(root: Path) -> dict[str, int]:
    from tests.workflow.test_workflow_run import _write_bundle

    manifest, state = _write_bundle(root, phase="READY", task_status="READY")
    argv = [
        "workflow",
        "continue",
        "--state",
        str(state),
        "--manifest",
        str(manifest),
        "--lock",
        str(manifest.with_name("plan.lock.json")),
        "--operation-id",
        "stable-projection",
        "--source-revision",
        "source",
        "--reason",
        "release probe",
    ]
    return {
        "success": _observed_case(root, [*argv, "--expected-revision", "1"], "status", "READY"),
        "refusal": _observed_case(root, [*argv, "--expected-revision", "2"], "status", "BLOCKED"),
    }


def _plan_cases(root: Path) -> dict[str, int]:
    from tests.cli.test_plan_verification_commands import _write_inputs

    manifest, lock, acceptance = _write_inputs(root)
    argv = [
        "plan",
        "verify",
        "--manifest",
        str(manifest),
        "--acceptance",
        str(acceptance),
        "--repository-root",
        str(root),
    ]
    success = _observed_case(root, [*argv, "--lock", str(lock)], "status", "PASS")
    missing = root / "absent-lock.json"
    refusal = _observed_case(root, [*argv, "--lock", str(missing)], "schemaVersion", "agent-lifecycle-error.v1")
    return {"success": success, "refusal": refusal}


def _model_cases(root: Path) -> dict[str, dict[str, int]]:
    request = {
        "schemaVersion": "agent-lifecycle-model-route-request.v1",
        "operationId": "release-probe",
        "phase": "triage",
        "sddTier": "S0",
        "riskFlags": {},
        "capabilityRequirements": ["text", "json"],
        "targetContextWindow": "8k",
        "routingPolicy": "balanced",
        "budgetClass": "normal",
        "userPolicy": {"localModelsAllowed": False, "cloudModelsAllowed": True},
    }
    write_json(root / "request.json", request)
    route = ["model", "route", "--request", "request.json"]
    success, decision = _invoke_case(root, route)
    if decision.get("schemaVersion") != "agent-lifecycle-model-route-decision.v1":
        raise ValueError("Stable route probe did not reach a decision")
    refusal = _observed_case(root, [*route[:3], "unreadable.json"], "schemaVersion", "agent-lifecycle-error.v1")

    receipt = {
        "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
        "operationId": "release-probe",
        "host": "fixture",
        "modelClass": decision["modelClass"],
        "providerModelHash": "a" * 64,
        "routeDecisionDigest": decision["decisionDigest"],
        "usage": {
            "inputTokens": 1,
            "outputTokens": 1,
            "billableTokens": 2,
            "cumulativeContextBytes": 10,
            "toolCalls": 0,
            "wallSeconds": 1,
        },
        "attestation": {"source": "host", "status": "ATTESTED"},
    }
    write_json(root / "decision.json", decision)
    argv = ["model", "usage-check", "--receipt", "usage.json", "--route-decision", "decision.json"]
    write_json(root / "usage.json", receipt)
    usage_success = _observed_case(root, argv, "status", "PASS")
    write_json(root / "usage.json", {**receipt, "attestation": {"source": "host", "status": "MISSING"}})
    usage_refusal = _observed_case(root, argv, "code", "model-usage-validation-failed")
    return {
        "model route": {"success": success, "refusal": refusal},
        "model usage-check": {"success": usage_success, "refusal": usage_refusal},
    }


def observe_stable_exits() -> dict[str, dict[str, int]]:
    """Run the fixed success and refusal fixtures in a fresh disposable root."""
    with tempfile.TemporaryDirectory(prefix="alk-stable-cli-") as name:
        root = Path(name)
        return {
            "version": {"success": _observed_case(root, ["version"], "schemaVersion", "agent-lifecycle-version.v1")},
            "plan verify": _plan_cases(root),
            "workflow continue": _workflow_cases(root),
            **_model_cases(root),
        }


def _owned(row: dict[str, Any]) -> bool:
    return bool(row["owner"]) and _VERSION.fullmatch(row["introducedIn"]) is not None


def _command_findings(
    commands: list[dict[str, Any]],
    schema_ids: set[str],
    observed_exits: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    root = build_parser()
    blockers: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in commands:
        path = row["path"]
        key = tuple(path)
        command = " ".join(path)
        if not key or key in seen or not _owned(row):
            blockers.append({"code": "stable-command-metadata-invalid", "command": command})
            continue
        seen.add(key)
        if not set(row["schemas"]) <= schema_ids:
            blockers.append({"code": "stable-command-schema-unlisted", "command": command})
        leaf = _leaf(root, path)
        if leaf is None:
            blockers.append({"code": "stable-command-missing", "command": command})
            continue
        supported = {flag for action in leaf._actions for flag in action.option_strings}
        missing = sorted(set(row["flags"]) - supported)
        if missing:
            blockers.append({"code": "stable-flag-missing", "command": command, "flags": missing})
        expected = row["exitCodes"]
        observed = observed_exits.get(command)
        if expected != observed:
            blockers.append(
                {"code": "stable-exit-changed", "command": command, "expected": expected, "observed": observed}
            )
    return blockers


def _schema_findings(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in schemas:
        schema_id = row["schemaId"]
        if schema_id in seen or not _owned(row):
            blockers.append({"code": "stable-schema-metadata-invalid", "schemaId": schema_id})
            continue
        seen.add(schema_id)
        try:
            actual = get_schema(schema_id)
        except LifecycleError:
            blockers.append({"code": "stable-schema-missing", "schemaId": schema_id})
            continue
        if set(actual.get("required", [])) - set(row["required"]):
            blockers.append({"code": "stable-schema-new-required-field", "schemaId": schema_id})
        if digest_value(actual) != row["schemaDigest"]:
            blockers.append({"code": "stable-schema-changed", "schemaId": schema_id})
    return blockers


def _python_matches(inventory: dict[str, Any], policy: dict[str, Any]) -> bool:
    modules = inventory["modules"]
    if inventory["sourcePolicy"] != PYTHON_POLICY.as_posix():
        return False
    declared = [
        (row["module"], sorted(export["name"] for export in row["exports"]))
        for row in modules
        if row["owner"] == row["module"] and all(_VERSION.fullmatch(item["introducedIn"]) for item in row["exports"])
    ]
    supported = [(row["module"], sorted(row["exports"])) for row in policy["modules"]]
    return len(declared) == len(modules) and sorted(declared) == sorted(supported)


def validate_stable_surface(
    surface: dict[str, Any],
    python_policy: dict[str, Any],
    expected_digest: str,
    *,
    guide: str,
    observed_exits: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """Validate an inventory against its reviewed digest and package interfaces."""
    digest = digest_value(surface)
    blockers: list[dict[str, Any]] = []
    if digest != expected_digest:
        blockers.append({"code": "stable-surface-digest-mismatch", "expected": expected_digest})
    try:
        if surface["schemaVersion"] != SCHEMA or not surface["commands"] or not surface["schemas"]:
            blockers.append({"code": "stable-surface-shape-invalid"})
        else:
            schemas = surface["schemas"]
            schema_ids = {row["schemaId"] for row in schemas}
            expected_commands, expected_schemas = external_classification(guide)
            command_names = {" ".join(row["path"]) for row in surface["commands"]}
            if command_names != expected_commands:
                blockers.append(
                    {
                        "code": "stable-command-classification-mismatch",
                        "missing": sorted(expected_commands - command_names),
                        "extra": sorted(command_names - expected_commands),
                    }
                )
            if schema_ids != expected_schemas:
                blockers.append(
                    {
                        "code": "stable-schema-classification-mismatch",
                        "missing": sorted(expected_schemas - schema_ids),
                        "extra": sorted(schema_ids - expected_schemas),
                    }
                )
            blockers.extend(_command_findings(surface["commands"], schema_ids, observed_exits))
            blockers.extend(_schema_findings(schemas))
            if not _python_matches(surface["pythonApi"], python_policy):
                blockers.append({"code": "stable-python-policy-mismatch"})
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        blockers.append({"code": "stable-surface-shape-invalid"})
    return {
        "schemaVersion": "agent-stable-surface-validation.v1",
        "status": "FAIL" if blockers else "PASS",
        "surfaceDigest": digest,
        "observedExits": observed_exits,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = validate_stable_surface(
        load_json(SURFACE),
        load_json(PYTHON_POLICY),
        args.expected_digest,
        guide=Path("docs/guides/ai-sdlc-integration.md").read_text(encoding="utf-8"),
        observed_exits=observe_stable_exits(),
    )
    write_json(args.evidence, result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
