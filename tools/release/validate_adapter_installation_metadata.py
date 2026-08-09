from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from release_common import ROOT, digest_value, file_identity, load_json, write_json
from agent_lifecycle.host_protocol import validate_adapter_descriptor
from agent_lifecycle.host_protocol.validation import validate_installation_facts

FORBIDDEN_CATALOG_IMPORTS = {
    "os",
    "subprocess",
    "agent_lifecycle.adapter_sessions.process",
}
FORBIDDEN_CATALOG_CALLS = {"Popen", "run", "run_process", "spawn", "system"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor-root", default="adapters")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    descriptor_root = Path(args.descriptor_root)
    descriptors = sorted(descriptor_root.glob("*/adapter.descriptor.json"))
    blockers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for path in descriptors:
        descriptor = load_json(path)
        descriptor_validation = validate_adapter_descriptor(descriptor)
        installation_validation = validate_installation_facts(descriptor.get("installation"))
        if descriptor_validation["status"] != "PASS":
            blockers.append({"code": "adapter-descriptor-invalid", "path": path.as_posix(), "blockers": descriptor_validation["blockers"]})
        if installation_validation["status"] != "PASS":
            blockers.append(
                {
                    "code": "adapter-installation-facts-invalid",
                    "path": path.as_posix(),
                    "blockers": installation_validation["blockers"],
                }
            )
        installation = descriptor.get("installation") if isinstance(descriptor.get("installation"), dict) else {}
        rows.append(
            {
                "adapterId": descriptor.get("adapterId"),
                "host": descriptor.get("host"),
                "binaryAliases": installation.get("binaryAliases"),
                "commandCount": len(installation.get("commands", [])) if isinstance(installation.get("commands"), list) else 0,
                "identity": file_identity(path),
            }
        )
    if not descriptors:
        blockers.append({"code": "adapter-descriptors-missing", "message": "no adapter descriptors found"})

    catalog_path = ROOT / "src/agent_lifecycle/diagnostics/installation_catalog.py"
    blockers.extend(_catalog_boundary_blockers(catalog_path))
    catalog_identity = file_identity(catalog_path)
    catalog_identity["path"] = catalog_path.relative_to(ROOT).as_posix()
    body = {
        "schemaVersion": "agent-adapter-installation-metadata-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "adapterCount": len(descriptors),
        "adapters": rows,
        "catalog": catalog_identity,
        "requiredInvariants": {
            "descriptorOwned": True,
            "argvArraysOnly": True,
            "diagnosticsHostExecution": False,
        },
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _catalog_boundary_blockers(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return [{"code": "installation-catalog-missing", "path": path.as_posix()}]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    blockers: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_CATALOG_IMPORTS:
                    blockers.append({"code": "installation-catalog-process-import", "path": path.as_posix(), "module": alias.name})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in FORBIDDEN_CATALOG_IMPORTS:
                blockers.append({"code": "installation-catalog-process-import", "path": path.as_posix(), "module": module})
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in FORBIDDEN_CATALOG_CALLS:
                blockers.append({"code": "installation-catalog-process-call", "path": path.as_posix(), "call": name})
    return blockers


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


if __name__ == "__main__":
    raise SystemExit(main())
