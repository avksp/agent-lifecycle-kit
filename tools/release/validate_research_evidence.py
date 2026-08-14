"""Validate one bounded research evidence package for release evidence."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from release_common import digest_value, write_json

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.research import load_evidence_package, read_source_snapshot, validate_evidence_package


_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


def validate_release_research_evidence(*, root: Path) -> dict[str, Any]:
    """Validate root/research-evidence.json and optional root/snapshots files."""

    try:
        package = load_evidence_package(root / "research-evidence.json")
        snapshots = _load_snapshots(root / "snapshots", package)
        return validate_evidence_package(package, snapshots=snapshots)
    except LifecycleError as exc:
        body = {
            "schemaVersion": "agent-research-evidence-validation.v1",
            "status": "FAIL",
            "packageDigest": None,
            "bindingChecks": [],
            "provenanceChecks": [],
            "lifecycleChecks": [],
            "securityChecks": [],
            "blockers": [{"code": exc.code, "message": str(exc)}],
            "productionPromotionClaimed": False,
        }
        return {**body, "validationDigest": digest_value(body)}


def _load_snapshots(snapshots_dir: Path, package: dict[str, Any]) -> dict[str, bytes]:
    snapshots: dict[str, bytes] = {}
    for source in package.get("sources", []):
        if not isinstance(source, dict) or source.get("snapshotDigest") is None:
            continue
        source_id = source.get("sourceId")
        if not isinstance(source_id, str) or not _SAFE_SOURCE_ID.fullmatch(source_id):
            continue
        path = snapshots_dir / f"{source_id}.txt"
        if path.is_file():
            snapshots[source_id] = read_source_snapshot(path)
    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_release_research_evidence(root=Path(args.root))
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
