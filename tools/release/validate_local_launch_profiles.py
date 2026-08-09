from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile  # noqa: E402
from release_common import digest_value, file_identity, load_json, write_json  # noqa: E402

EXPECTED = {
    "valid.json": ("PASS", None),
    "path-escape.json": ("FAIL", "local-launch-profile-executable"),
    "shell-command.json": ("FAIL", "local-launch-profile-shell-executable"),
    "unknown-placeholder.json": ("FAIL", "local-launch-profile-placeholder"),
    "env-wildcard.json": ("FAIL", "local-launch-profile-env-pattern"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)

    fixture_root = Path(args.fixtures)
    blockers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for name, (expected_status, expected_code) in EXPECTED.items():
        path = fixture_root / name
        if not path.is_file():
            blockers.append({"code": "local-launch-fixture-missing", "fixture": name})
            continue
        validation = validate_local_launch_profile(load_json(path))
        codes = sorted(item.get("code") for item in validation["blockers"] if isinstance(item.get("code"), str))
        if validation["status"] != expected_status:
            blockers.append(
                {
                    "code": "local-launch-fixture-status-mismatch",
                    "fixture": name,
                    "expected": expected_status,
                    "actual": validation["status"],
                }
            )
        if expected_code is not None and expected_code not in codes:
            blockers.append(
                {
                    "code": "local-launch-fixture-blocker-missing",
                    "fixture": name,
                    "expectedBlocker": expected_code,
                }
            )
        rows.append(
            {
                "fixture": file_identity(path),
                "expectedStatus": expected_status,
                "actualStatus": validation["status"],
                "expectedBlocker": expected_code,
                "blockerCodes": codes,
                "profileDigest": validation["profileDigest"],
            }
        )
    unexpected = sorted(path.name for path in fixture_root.glob("*.json") if path.name not in EXPECTED)
    if unexpected:
        blockers.append({"code": "local-launch-fixture-unexpected", "fixtures": unexpected})
    body = {
        "schemaVersion": "agent-local-host-launch-fixture-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "fixtureCount": len(rows),
        "fixtures": rows,
        "blockers": blockers,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
