"""Validate a local Agent Plugins package and its pinned schema provenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_plugin_package import provenance_for_schema, validate_archive, validate_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a portable Agent Plugins package.")
    parser.add_argument("--package", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--archive")
    parser.add_argument("--root", default=".", help="repository root for schema provenance")
    parser.add_argument("--version", help="expected package version")
    args = parser.parse_args()

    package = Path(args.package)
    package_result = validate_package(package, expected_version=args.version)
    provenance_result = provenance_for_schema(Path(args.root).resolve())
    archive_result = None
    if args.archive:
        archive_result = validate_archive(
            Path(args.archive),
            package_root=package,
            expected_version=args.version,
        )
    blockers = list(package_result["blockers"])
    blockers.extend(provenance_result["blockers"])
    if archive_result is not None:
        blockers.extend(archive_result["blockers"])
    result = {
        "schemaVersion": "agent-plugin-validation-evidence.v1",
        "status": "PASS" if not blockers else "FAIL",
        "package": package_result,
        "schemaProvenance": provenance_result,
        "archive": archive_result,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
