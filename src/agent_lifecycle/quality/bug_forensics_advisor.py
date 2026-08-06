"""Deterministic advisory policy for optional Bug Forensics."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest

BUG_FORENSICS_ADVISORY_SCHEMA = "agent-bug-forensics-advisory.v1"
BUG_FORENSICS_PROFILE_ID = "bug-forensics"

_BUG_MARKERS = (
    ("defect-signal-bug", ("bug", "defect", "failure", "failing", "error", "crash", "broken", "баг", "ошиб", "падает", "сбой")),
    ("defect-signal-regression", ("regression", "regressed", "again fails", "раньше работало", "регресс")),
    ("defect-signal-flaky", ("flaky", "intermittent", "non-deterministic", "passes on retry", "unstable test", "нестабиль", "иногда падает")),
    ("defect-signal-incident", ("incident", "outage", "production issue", "rollback", "hotfix", "инцидент", "авар")),
    (
        "defect-signal-security-bug",
        ("security bug", "vulnerability", "xss", "csrf", "sql injection", "token leak", "secret leak", "уязвим"),
    ),
)

_EVIDENCE_EXPECTATIONS = (
    "reproduction-before-modification",
    "failure-fingerprint",
    "hypothesis-ledger",
    "same-fingerprint-regression-proof",
    "fix-impact-reference",
)


def build_bug_forensics_advisory(text: str, *, source_label: str = "task") -> dict[str, Any]:
    """Recommend Bug Forensics from task text without activating workflow gates."""

    matches = _matches(text)
    suggested = bool(matches)
    reason_codes = [item["reasonCode"] for item in matches] or ["no-defect-signal"]
    if suggested:
        reason_codes.append("bug-forensics-advisory-only")
    body = {
        "schemaVersion": BUG_FORENSICS_ADVISORY_SCHEMA,
        "status": "PASS",
        "sourceLabel": source_label,
        "recommendation": "SUGGEST" if suggested else "NOT_APPLICABLE",
        "profileId": BUG_FORENSICS_PROFILE_ID,
        "recommendedQualityProfiles": [BUG_FORENSICS_PROFILE_ID] if suggested else [],
        "detectedTaskShape": "bugfix" if suggested else None,
        "matchedSignals": matches,
        "reasonCodes": reason_codes,
        "evidenceExpectations": list(_EVIDENCE_EXPECTATIONS) if suggested else [],
        "gateBoundary": {
            "advisoryOnly": True,
            "activeWorkflowGateClaimed": False,
            "blockingRequiresReviewedPlanOptIn": True,
            "enabledByDefault": False,
        },
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "rawTaskTextStored": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "advisoryDigest": canonical_digest(body)}


def bug_forensics_recommended(advisory: dict[str, Any]) -> bool:
    """Return whether an advisory suggests the existing Bug Forensics profile."""

    return advisory.get("recommendation") == "SUGGEST" and BUG_FORENSICS_PROFILE_ID in advisory.get("recommendedQualityProfiles", [])


def _matches(text: str) -> list[dict[str, str]]:
    lowered = text.lower()
    matches: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for reason_code, markers in _BUG_MARKERS:
        for marker in markers:
            if marker in lowered and (reason_code, marker) not in seen:
                matches.append({"reasonCode": reason_code, "signal": marker})
                seen.add((reason_code, marker))
    return matches[:12]


__all__ = [
    "BUG_FORENSICS_ADVISORY_SCHEMA",
    "BUG_FORENSICS_PROFILE_ID",
    "bug_forensics_recommended",
    "build_bug_forensics_advisory",
]
