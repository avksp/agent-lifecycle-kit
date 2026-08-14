"""Validate built-in workflow presets without model, network or host calls."""

from __future__ import annotations

import argparse
import copy
import json
import tempfile
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.project_profile_schemas import PROJECT_PROFILE_PRESET_IDS
from agent_lifecycle.project.presets import (
    build_preset_profile_draft,
    load_project_preset,
    render_project_preset,
    validate_project_preset,
)


def validate(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    presets: dict[str, dict[str, Any]] = {}
    for preset_id in PROJECT_PROFILE_PRESET_IDS:
        try:
            preset = load_project_preset(preset_id, project_root=Path.cwd())
            presets[preset_id] = preset
            validation = validate_project_preset(preset)
            check = {"presetId": preset_id, "status": validation["status"], "validation": validation}
        except (LifecycleError, OSError, TypeError, ValueError) as exc:  # pragma: no cover - defensive release boundary
            check = {"presetId": preset_id, "status": "FAIL", "blockers": [{"code": "preset-read-failed", "errorType": type(exc).__name__}]}
        checks.append(check)
        blockers.extend(check.get("validation", {}).get("blockers", []) if isinstance(check.get("validation"), dict) else check.get("blockers", []))

    expected = {
        "quick-change": ("implement", "S0", "off", "requires-frozen-plan", {"implementation", "audit"}),
        "research-review": ("research", "S1", "parallel-research-synthesis", "excluded", {"research", "planning", "review"}),
        "feature-implementation": ("implement", "S2", "implementation-audit-panel", "requires-frozen-plan", {"planning", "implementation", "audit"}),
    }
    for preset_id, values in expected.items():
        preset = presets.get(preset_id)
        if preset is None:
            continue
        actual = (preset.get("defaultMode"), preset.get("defaultRisk"), preset.get("reviewMesh"), preset.get("implementationAuthority"), set(preset.get("stages", {})))
        if actual != values:
            blockers.append({"code": "preset-default-matrix-mismatch", "presetId": preset_id, "expected": list(values), "actual": list(actual)})
        if "qualityFloor" in preset:
            blockers.append({"code": "preset-quality-floor-field-present", "presetId": preset_id})
        draft = build_preset_profile_draft(preset, project_root=root)
        if draft.get("defaultMode") != preset["defaultMode"]:
            blockers.append({"code": "preset-draft-mode-mismatch", "presetId": preset_id})

    if presets:
        unsafe = copy.deepcopy(next(iter(presets.values())))
        unsafe["credentials"] = "not allowed"
        unsafe["presetDigest"] = canonical_digest({key: value for key, value in unsafe.items() if key != "presetDigest"})
        unsafe_result = validate_project_preset(unsafe)
        if unsafe_result["status"] != "FAIL":
            blockers.append({"code": "sensitive-preset-field-accepted"})

        with tempfile.TemporaryDirectory(dir=root if root.is_dir() else None) as directory:
            output = Path(directory) / "profile.json"
            receipt = render_project_preset(
                next(iter(presets)),
                output_path=output,
                project_root=Path(directory),
            )
            if receipt["status"] != "PASS" or not output.is_file():
                blockers.append({"code": "preset-render-failed"})

    body = {
        "schemaVersion": "agent-project-workflow-presets-release-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "presetCount": len(presets),
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    result = validate(args.root.resolve())
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
