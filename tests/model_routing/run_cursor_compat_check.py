from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_lifecycle.contracts import canonical_digest, read_json_object  # noqa: E402

EXPECTED_MODELS = {
    "strong-reasoning": "glm-5.2-max",
    "specialist-review": "glm-5.2-max",
    "standard-code": "glm-5.2-high",
    "budget": "glm-5.2-high",
}
CRITICAL_PHASES = {
    "s2-specification",
    "independent-review",
    "security-review",
    "performance-review",
    "production-promotion",
    "final-audit",
}
APPROVED_DOWNSHIFT_PHASES = {"coding-plan", "implementation-planning"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cursor-audit", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    source = _select_source(Path(args.cursor_audit), Path(args.fixture))
    checks = _validate_cursor_compat(source["payload"])
    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    evidence = {
        "schemaVersion": "agent-cursor-compat-evidence.v1",
        "status": status,
        "source": {
            "kind": source["kind"],
            "path": source["path"].as_posix(),
            "digest": canonical_digest(source["payload"]),
            "fallbackReason": source["fallbackReason"],
        },
        "checks": checks,
        "providerModelHashes": _provider_model_hashes(source["payload"]),
        "productionPromotionClaimed": False,
    }
    path = Path(args.evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


def _select_source(cursor_audit: Path, fixture: Path) -> dict[str, Any]:
    fallback_reason = "cursor-audit-missing"
    if cursor_audit.is_file():
        audit = read_json_object(cursor_audit, label="cursor promotion audit")
        selections = audit.get("modelSelections")
        if audit.get("status") == "PASS" and isinstance(selections, list) and selections:
            return {"kind": "release-0-3-audit", "path": cursor_audit, "payload": audit, "fallbackReason": None}
        fallback_reason = _audit_fallback_reason(audit)
    return {
        "kind": "fixture",
        "path": fixture,
        "payload": read_json_object(fixture, label="cursor compatibility fixture"),
        "fallbackReason": fallback_reason,
    }


def _audit_fallback_reason(audit: dict[str, Any]) -> str:
    status = audit.get("status")
    if status != "PASS":
        return f"cursor-audit-{str(status or 'missing-status').lower()}"
    return "cursor-audit-missing-model-selections"


def _validate_cursor_compat(payload: dict[str, Any]) -> list[dict[str, Any]]:
    selections = payload.get("modelSelections")
    checks = [
        _check("host-is-cursor", payload.get("host") == "cursor"),
        _check("no-production-promotion-claim", payload.get("productionPromotionClaimed") is False),
        _check("model-selections-present", isinstance(selections, list) and bool(selections)),
    ]
    if not isinstance(selections, list):
        return checks

    by_class: dict[str, list[dict[str, Any]]] = {}
    for item in selections:
        if isinstance(item, dict):
            model_class = item.get("modelClass")
            if isinstance(model_class, str):
                by_class.setdefault(model_class, []).append(item)

    for model_class, expected_model in EXPECTED_MODELS.items():
        candidates = by_class.get(model_class, [])
        checks.append(_check(f"{model_class}-binding-present", bool(candidates)))
        if candidates:
            checks.append(
                _check(
                    f"{model_class}-binding-matches-expected-family",
                    all(item.get("providerModel") == expected_model for item in candidates),
                )
            )

    checks.append(_check("critical-phases-use-strong-binding", _critical_phases_are_strong(selections)))
    checks.append(_check("downshift-is-non-critical-only", _downshift_is_non_critical(selections)))
    checks.append(_check("provider-models-redactable", all(_provider_model(item) for item in selections if isinstance(item, dict))))
    return checks


def _critical_phases_are_strong(selections: list[Any]) -> bool:
    for item in selections:
        if not isinstance(item, dict):
            return False
        phase = item.get("phase")
        critical = item.get("critical") is True or phase in CRITICAL_PHASES
        if not critical:
            continue
        if item.get("providerModel") != "glm-5.2-max":
            return False
        if item.get("modelClass") not in {"strong-reasoning", "specialist-review"}:
            return False
    return True


def _downshift_is_non_critical(selections: list[Any]) -> bool:
    for item in selections:
        if not isinstance(item, dict) or item.get("fallbackFrom") != "glm-5.2-max":
            continue
        if item.get("providerModel") != "glm-5.2-high":
            return False
        if item.get("critical") is True:
            return False
        if item.get("phase") not in APPROVED_DOWNSHIFT_PHASES:
            return False
    return True


def _provider_model_hashes(payload: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    selections = payload.get("modelSelections", [])
    if not isinstance(selections, list):
        return hashes
    for index, item in enumerate(selections, start=1):
        if not isinstance(item, dict):
            continue
        provider_model = _provider_model(item)
        if provider_model is None:
            continue
        model_class = str(item.get("modelClass", "unknown"))
        phase = str(item.get("phase", f"selection-{index}"))
        hashes[f"{model_class}:{phase}"] = canonical_digest({"providerModel": provider_model})
    return hashes


def _provider_model(item: dict[str, Any]) -> str | None:
    value = item.get("providerModel")
    return value if isinstance(value, str) and value else None


def _check(name: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if passed else "FAIL"}


if __name__ == "__main__":
    raise SystemExit(main())
