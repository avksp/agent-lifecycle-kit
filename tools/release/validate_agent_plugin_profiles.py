"""Validate the shipped Agent Plugins client profiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_lifecycle.contracts import read_json_object
from agent_lifecycle.contracts.agent_plugin_qualification_schemas import validate_qualification_profile


EXPECTED_ADAPTERS = {"codex", "claude", "cursor"}


def validate_profiles(paths: list[Path]) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    blockers: list[dict[str, object]] = []
    seen: set[str] = set()
    for path in paths:
        try:
            profile = read_json_object(path, label="Agent Plugins qualification profile")
            validation = validate_qualification_profile(profile)
            adapter_id = profile.get("adapterId")
            if adapter_id in seen:
                validation["blockers"].append({"code": "duplicate-profile-adapter", "adapterId": adapter_id})
                validation["status"] = "FAIL"
            if isinstance(adapter_id, str):
                seen.add(adapter_id)
            check = {"path": path.as_posix(), "adapterId": adapter_id, "status": validation["status"], "validation": validation}
        except Exception as exc:  # pragma: no cover - defensive CLI boundary
            check = {"path": path.as_posix(), "status": "FAIL", "blockers": [{"code": "profile-read-failed", "errorType": type(exc).__name__}]}
        checks.append(check)
        blockers.extend(check.get("validation", {}).get("blockers", []) if isinstance(check.get("validation"), dict) else check.get("blockers", []))
    missing = sorted(EXPECTED_ADAPTERS - seen)
    if missing:
        blockers.append({"code": "profile-adapter-set-mismatch", "missing": missing})
    unexpected = sorted(seen - EXPECTED_ADAPTERS)
    if unexpected:
        blockers.append({"code": "profile-adapter-set-mismatch", "unexpected": unexpected})
    return {
        "schemaVersion": "agent-plugin-qualification-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Agent Plugins qualification profiles.")
    parser.add_argument("--profiles", nargs="+", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_profiles([Path(item) for item in args.profiles])
    result["validationDigest"] = __import__("agent_lifecycle.contracts", fromlist=["canonical_digest"]).canonical_digest(result)
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
