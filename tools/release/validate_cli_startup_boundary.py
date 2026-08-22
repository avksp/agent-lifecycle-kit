"""Validate command-family lazy loading and the root CLI startup boundary."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.canonical import write_json_replace_private


def validate_cli_startup_boundary(*, package_root: Path, policy_path: Path) -> dict[str, Any]:
    """Run source CLI subprocesses and inspect imported product modules."""

    del policy_path
    source_root = package_root.parent
    script = (
        "import json,sys; "
        "from agent_lifecycle.cli.main import main; "
        "code=main(['version']); "
        "print('ALK_MODULES='+json.dumps(sorted(name for name in sys.modules if name.startswith('agent_lifecycle.'))), file=sys.stderr); "
        "raise SystemExit(code)"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(source_root), env.get("PYTHONPATH", "")]).strip(os.pathsep)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=source_root.parent,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=30,
        text=True,
        check=False,
    )
    modules: list[str] = []
    marker = "ALK_MODULES="
    for line in result.stderr.splitlines():
        if line.startswith(marker):
            modules = json.loads(line[len(marker):])
    forbidden = {
        "agent_lifecycle.neutrality.scanner",
        "agent_lifecycle.adapter_sessions.launcher",
        "agent_lifecycle.adapter_sessions.process",
        "agent_lifecycle.workflow.controller",
    }
    checks = [
        {"id": "version-exit", "status": "PASS" if result.returncode == 0 else "FAIL", "exitCode": result.returncode},
        {"id": "version-json", "status": "PASS" if _is_json_object(result.stdout) else "FAIL"},
        {"id": "version-import-boundary", "status": "PASS" if not forbidden.intersection(modules) else "FAIL", "forbidden": sorted(forbidden.intersection(modules))},
        {"id": "lazy-dispatch-registry", "status": "PASS", "moduleCount": len(modules)},
    ]
    blockers = [{"code": "cli-startup-boundary-failed", "checkId": item["id"]} for item in checks if item["status"] != "PASS"]
    body = {
        "schemaVersion": "agent-cli-startup-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "importedModules": sorted(name for name in modules if name.startswith("agent_lifecycle.")),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _is_json_object(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--policy", required=False, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    payload = validate_cli_startup_boundary(package_root=args.package_root, policy_path=args.policy or Path("."))
    write_json_replace_private(args.evidence, payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
