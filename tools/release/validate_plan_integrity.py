"""Validate canonical plan checks and their regression discrimination."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, load_json, write_json
except ModuleNotFoundError:  # pragma: no cover
    from tools.release.release_common import digest_value, load_json, write_json

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.ownership_paths import normalize_authority_path
from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract
from agent_lifecycle.planning.traceability import validate_plan_traceability
from agent_lifecycle.planning.verification import build_plan_verification
from agent_lifecycle.freeze import verify_plan_package_integrity


VALIDATION_SCHEMA = "agent-plan-integrity-regression-validation.v1"


def validate_plan_integrity(
    *,
    repository_root: Path,
    package_root: Path,
    manifest_path: Path,
    acceptance_path: Path,
    lock_path: Path,
) -> dict[str, Any]:
    """Run a positive package verification and bounded negative mutations."""

    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    try:
        manifest = load_json(manifest_path)
        lock = load_json(lock_path)
        acceptance = acceptance_path.read_text(encoding="utf-8")
        positive = build_plan_verification(
            manifest,
            manifest_path=manifest_path,
            lock=lock,
            acceptance_markdown=acceptance,
            repository_root=repository_root,
            package_root=package_root,
        )
        checks.append({"id": "canonical-plan-verification", "status": positive["status"], "blockers": positive["blockers"]})
        if positive["status"] != "PASS":
            blockers.append({"code": "canonical-plan-verification-failed", "context": positive["blockers"]})
        for mutation in _mutations(manifest, lock, repository_root):
            result = mutation["run"]()
            observed = _observed_codes(result)
            expected = mutation["expected"]
            passed = bool(set(expected).intersection(observed))
            checks.append({"id": mutation["id"], "status": "PASS" if passed else "FAIL", "expectedBlockerCodes": expected, "observedBlockerCodes": sorted(observed)})
            if not passed:
                blockers.append({"code": "mutation-not-discriminated", "context": {"id": mutation["id"], "expected": expected, "observed": sorted(observed)}})
    except (LifecycleError, OSError, KeyError, TypeError, ValueError) as exc:
        blockers.append({"code": getattr(exc, "code", "plan-integrity-validation-failed"), "message": getattr(exc, "message", str(exc)), "context": getattr(exc, "details", {})})
        checks.append({"id": "plan-integrity-inputs", "status": "FAIL"})
    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "repositoryRoot": repository_root.resolve().as_posix(),
        "packageRoot": package_root.resolve().as_posix(),
        "manifest": manifest_path.as_posix(),
        "acceptance": acceptance_path.as_posix(),
        "lock": lock_path.as_posix(),
        "checks": checks,
        "blockers": blockers,
        "cleanCloneFixtures": True,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _mutations(
    manifest: dict[str, Any],
    lock: dict[str, Any],
    repository_root: Path,
) -> list[dict[str, Any]]:
    graph = _graph_fixture(repository_root)

    def unknown_authority() -> dict[str, Any]:
        candidate = copy.deepcopy(manifest)
        candidate["integrationSeams"] = ["controller"]
        return validate_plan_manifest_contract(candidate)

    def orphan_requirement() -> dict[str, Any]:
        candidate = copy.deepcopy(graph)
        candidate["specification"]["requirements"].append({"id": "REQ-ORPHAN", "description": "unused"})
        return validate_plan_traceability(candidate)

    def pseudo_glob() -> dict[str, Any]:
        try:
            normalize_authority_path("src/agent_lifecycle/**")
        except LifecycleError as exc:
            return {"status": "FAIL", "blockers": [{"code": exc.code}]}
        return {"status": "PASS", "blockers": []}

    def lock_drift() -> dict[str, Any]:
        candidate = copy.deepcopy(lock)
        entries = candidate.get("entries")
        if isinstance(entries, list) and entries:
            entries[0] = {**entries[0], "bytes": int(entries[0]["bytes"]) + 1}
        try:
            verify_plan_package_integrity(manifest, candidate, repository_root=repository_root)
        except LifecycleError as exc:
            return {"status": "FAIL", "blockers": [{"code": exc.code}]}
        return {"status": "PASS", "blockers": []}

    return [
        {"id": "unknown-authority-field", "expected": ["plan-manifest-authority-field-unknown"], "run": unknown_authority},
        {"id": "orphan-requirement", "expected": ["traceability-requirement-orphan"], "run": orphan_requirement},
        {"id": "pseudo-glob-authority", "expected": ["invalid-authority-path"], "run": pseudo_glob},
        {
            "id": "package-lock-byte-drift",
            "expected": ["plan-package-files-mismatch", "plan-lock-inventory-mismatch"],
            "run": lock_drift,
        },
    ]


def _graph_fixture(repository_root: Path) -> dict[str, Any]:
    path = repository_root / "tests/planning/fixtures/canonical-plan-manifest.v1.json"
    manifest = load_json(path)
    manifest["finalAuditGates"] = ["[AC-1|EV-1] The bounded plan remains valid."]
    return manifest


def _observed_codes(result: dict[str, Any]) -> set[str]:
    return {item.get("code") for item in result.get("blockers", []) if isinstance(item, dict) and isinstance(item.get("code"), str)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--acceptance", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_plan_integrity(
        repository_root=Path.cwd(),
        package_root=Path(args.package_root),
        manifest_path=Path(args.manifest),
        acceptance_path=Path(args.acceptance),
        lock_path=Path(args.lock),
    )
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
