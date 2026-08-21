"""Validate read-only operator evidence for GitHub and PyPI protection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from release_common import digest_value, write_json


VALIDATION_SCHEMA = "agent-github-security-evidence-validation.v1"
INPUT_SCHEMA = "github-security-posture.v1"


def validate_github_security_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    if payload.get("schemaVersion") != INPUT_SCHEMA:
        blockers.append({"code": "github-evidence-schema-invalid"})
    source = payload.get("source")
    if not isinstance(source, dict) or source.get("kind") != "github-api-read-only":
        blockers.append({"code": "github-evidence-source-not-read-only"})
    if payload.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "github-evidence-production-claim"})

    checks.append({"id": "input-envelope", "status": "PASS" if not blockers else "FAIL"})
    for section, field in (
        ("main", "protected"),
        ("main", "administratorsCannotBypass"),
        ("main", "forcePushesDisabled"),
        ("main", "deletionsDisabled"),
        ("releaseRefs", "immutableTags"),
        ("releaseRefs", "protectedReleaseRefs"),
        ("actions", "immutablePins"),
        ("codeql", "required"),
        ("pypi", "trustedPublishing"),
        ("pypi", "environmentProtected"),
        ("pypi", "tagRestriction"),
        ("pypi", "selfReviewPrevented"),
        ("security", "secretScanning"),
        ("security", "pushProtection"),
        ("security", "dependencyUpdates"),
    ):
        value = _section_value(payload, section, field)
        status = "PASS" if value is True else "FAIL"
        checks.append({"id": f"{section}.{field}", "status": status})
        if status == "FAIL":
            blockers.append({"code": "github-protection-missing", "section": section, "field": field})

    main = payload.get("main") if isinstance(payload.get("main"), dict) else {}
    required_checks = main.get("requiredChecks")
    checks.append({"id": "main.required-checks", "status": "PASS" if _nonempty_strings(required_checks) else "FAIL"})
    if not _nonempty_strings(required_checks):
        blockers.append({"code": "main-required-checks-missing"})

    review = payload.get("reviewPosture") if isinstance(payload.get("reviewPosture"), dict) else {}
    maintainers = review.get("eligibleIndependentMaintainers")
    if not isinstance(maintainers, int) or isinstance(maintainers, bool) or maintainers < 0:
        blockers.append({"code": "review-posture-maintainer-count-invalid"})
        checks.append({"id": "review-posture", "status": "FAIL"})
    elif maintainers > 0:
        status = review.get("independentLatestPushApproval") is True
        checks.append({"id": "review-posture", "status": "PASS" if status else "FAIL", "eligibleIndependentMaintainers": maintainers})
        if not status:
            blockers.append({"code": "independent-latest-push-approval-missing"})
    else:
        compensation = review.get("singleMaintainerCompensatingControls")
        required = (
            "mandatoryChecksWithoutAdministratorBypass",
            "codeqlRequired",
            "immutableActionIdentities",
            "protectedReleaseRefs",
            "protectedPyPITrustedPublishing",
        )
        missing = [field for field in required if not isinstance(compensation, dict) or compensation.get(field) is not True]
        residual = compensation.get("residualRisk") if isinstance(compensation, dict) else None
        if not isinstance(residual, str) or not residual.strip():
            missing.append("residualRisk")
        checks.append({"id": "review-posture", "status": "PASS" if not missing else "FAIL", "eligibleIndependentMaintainers": 0, "missing": missing})
        if missing:
            blockers.append({"code": "single-maintainer-compensating-controls-incomplete", "missing": missing})

    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "repository": payload.get("repository"),
        "observedAt": payload.get("observedAt"),
        "sourceKind": source.get("kind") if isinstance(source, dict) else None,
        "checks": checks,
        "blockers": blockers,
        "externalEvidenceAccepted": not blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _section_value(payload: dict[str, Any], section: str, field: str) -> Any:
    value = payload.get(section)
    return value.get(field) if isinstance(value, dict) else None


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    path = Path(args.input)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    payload = validate_github_security_evidence(value if isinstance(value, dict) else {})
    payload["input"] = {"name": path.name}
    payload["validationDigest"] = digest_value({key: value for key, value in payload.items() if key != "validationDigest"})
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
