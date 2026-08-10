from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402


REQUIRED_MARKERS = {
    "start": ("planningTask", "explicit_launch", "task_text"),
    "planning-launch": (
        "MAX_TASK_INPUT_BYTES",
        "MAX_CAPTURED_OUTPUT_BYTES",
        "implementationAuthorized",
        "rawTaskTextStored",
    ),
    "launcher": (
        "require_planning_qualification_receipt",
        "capture_git_worktree_identity",
        "planning-launch-worktree-drift",
        "PLANNING_ONLY_QUALIFIED",
    ),
    "process": ("stdin_text", "max_input_bytes", "max_output_bytes", "subprocess.Popen"),
}


def validate_boundary(paths: dict[str, Path]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    for role, markers in REQUIRED_MARKERS.items():
        path = paths[role]
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=path.as_posix())
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            blockers.append({"code": "planning-boundary-source-invalid", "role": role, "errorType": type(exc).__name__})
            continue
        for marker in markers:
            if marker not in source:
                blockers.append({"code": "planning-boundary-marker-missing", "role": role, "marker": marker})
        if role == "process" and "shell=False" not in source:
            blockers.append({"code": "planning-boundary-shell-not-disabled", "role": role})
    body = {
        "schemaVersion": "agent-planning-launch-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "paths": {role: path.as_posix() for role, path in sorted(paths.items())},
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    for role in REQUIRED_MARKERS:
        parser.add_argument(f"--{role}", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    paths = {role: Path(getattr(args, role.replace("-", "_"))) for role in REQUIRED_MARKERS}
    report = validate_boundary(paths)
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
