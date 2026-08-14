"""Validate the offline benchmark qualification release boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_lifecycle.benchmarks import select_stratified_tasks, validate_stratified_sample
from agent_lifecycle.benchmarks.contracts import load_suite
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.schemas import get_schema


EXPECTED_SCHEMAS = (
    "agent-benchmark-run-receipt.v1",
    "agent-benchmark-stratified-sample.v1",
    "agent-benchmark-qualification.v1",
)


def validate_release(*, root: Path, evidence_path: Path) -> dict[str, Any]:
    repository_root = Path.cwd()
    suite_path = root / "benchmarks/reference-tasks/manifest.json"
    if not suite_path.is_file():
        suite_path = repository_root / "benchmarks/reference-tasks/manifest.json"
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    try:
        suite = load_suite(suite_path)
        shapes = {row.get("shape") for row in suite.payload["tasks"]}
        checks.append({"code": "suite-load", "status": "PASS", "taskCount": len(suite.payload["tasks"])})
        if len(suite.payload["tasks"]) < 5:
            blockers.append({"code": "reference-suite-too-small"})
        if len(shapes) < 5:
            blockers.append({"code": "reference-suite-shape-coverage", "shapes": sorted(item for item in shapes if isinstance(item, str))})
        sample = select_stratified_tasks(suite, seed="release-1-72", max_tasks=24, max_strata=16)
        sample_validation = validate_stratified_sample(sample)
        checks.append({"code": "stratified-sample", "status": sample_validation["status"], "sampleDigest": sample["sampleDigest"]})
        blockers.extend(sample_validation["blockers"])
    except Exception as exc:  # the release validator must return a typed report
        blockers.append({"code": "qualification-fixture-invalid", "detail": str(exc)})
        sample = None
    missing_schemas = []
    for schema_id in EXPECTED_SCHEMAS:
        try:
            get_schema(schema_id)
        except Exception:
            missing_schemas.append(schema_id)
    if missing_schemas:
        blockers.append({"code": "qualification-schema-missing", "schemas": missing_schemas})
    checks.append({"code": "schema-registry", "status": "PASS" if not missing_schemas else "FAIL", "schemas": list(EXPECTED_SCHEMAS)})
    body: dict[str, Any] = {
        "schemaVersion": "agent-benchmark-qualification-evidence.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "sample": sample,
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    result = {**body, "validationDigest": canonical_digest(body)}
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate offline benchmark qualification contracts.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_release(root=Path(args.root), evidence_path=Path(args.evidence))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
