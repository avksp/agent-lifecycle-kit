from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_qualified_planning_launch_profiles_base",
    ROOT / "tools/release/validate_qualified_planning_launch_profiles.py",
)
assert SPEC and SPEC.loader
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

TARGETS = (
    "claude",
    "codex",
    "cursor",
    "gemini-cli",
    "goose",
    "grok-build",
    "hermes",
    "kimi-code",
    "opencode",
    "openinterpreter",
    "pi",
    "qwen-code",
)


def validate_all_profiles(adapter_root: Path, *, repository_root: Path | None = None) -> dict[str, Any]:
    """Run the canonical profile checks over the complete bundled adapter set."""

    report = BASE.validate_profiles(
        adapter_root,
        repository_root=repository_root,
        targets=TARGETS,
    )
    report["schemaVersion"] = "agent-all-planning-launch-profile-validation.v1"
    report["adapterCount"] = len(report.get("profiles", []))
    report["validationDigest"] = BASE.canonical_digest(
        {key: value for key, value in report.items() if key != "validationDigest"}
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    report = validate_all_profiles(Path(args.adapter_root))
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
