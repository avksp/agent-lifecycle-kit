from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.release.validate_python_quality import validate_quality


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy(source_digest: str) -> dict:
    baseline = [{"path": "src/example.py", "code": "F401", "count": 0, "sourceDigest": source_digest}]
    return {
        "schemaVersion": "agent-python-quality-policy.v1",
        "revision": 1,
        "toolchain": {"ruff": "0.16.3", "mypy": "1.17.1", "coverage": "7.10.6"},
        "ruff": {
            "targetVersion": "py311",
            "lineLength": 120,
            "sourceRoots": ["src"],
            "firstParty": ["agent_lifecycle"],
            "correctnessSelectors": ["E4", "E7", "E9", "F", "B"],
            "migrationSelectors": ["I", "UP", "RUF", "SIM", "PTH", "ARG", "BLE"],
            "intentionalFindings": [],
            "correctnessBaseline": baseline,
            "migrationBaseline": [],
            "formatBaseline": [],
            "lineLengthBaseline": [],
        },
        "mypy": {"strictClean": [], "baseline": []},
        "coverage": {"minimumStatementLinePercent": 76.0, "baseline": {}},
        "limits": {"maxWallSeconds": 900, "maxOutputBytes": 16777216, "maxBaselineEntries": 20000},
        "productionPromotionClaimed": False,
    }


def _run_receipt() -> dict:
    return {
        "schemaVersion": "agent-python-quality-run.v1",
        "status": "PASS",
        "toolchain": {"ruff": "0.16.3", "mypy": "1.17.1", "coverage": "7.10.6"},
        "changedPaths": [],
        "commands": [],
        "artifacts": {
            "ruffCorrectness": "work/raw/ruff-correctness.stdout.json",
            "ruffMigration": "work/raw/ruff-migration.stdout.json",
            "ruffFormat": "work/raw/ruff-format.stdout.txt",
            "ruffLineLength": "work/raw/ruff-line-length.stdout.json",
            "mypy": "work/raw/mypy.stdout.txt",
            "coverage": "work/raw/coverage.json",
        },
    }


class PythonQualityValidatorTests(unittest.TestCase):
    def test_validator_accepts_bound_clean_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/example.py"
            source.parent.mkdir()
            source.write_text("value = 1\n", encoding="utf-8")
            raw = root / "work/raw"
            raw.mkdir(parents=True)
            for name in ("ruff-correctness.stdout.json", "ruff-migration.stdout.json", "ruff-line-length.stdout.json"):
                (raw / name).write_text("[]\n", encoding="utf-8")
            (raw / "ruff-format.stdout.txt").write_text("1 file already formatted\n", encoding="utf-8")
            (raw / "mypy.stdout.txt").write_text("Success: no issues found\n", encoding="utf-8")
            (raw / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 80.0}}), encoding="utf-8")
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(_policy(_digest(source))), encoding="utf-8")
            run_path = root / "run.json"
            run_path.write_text(json.dumps(_run_receipt()), encoding="utf-8")

            result = validate_quality(
                repository_root=root,
                policy_path=policy_path,
                run_receipt_path=run_path,
                work_root=root / "work",
            )

            self.assertEqual(result["status"], "PASS", result["blockers"])

    def test_validator_rejects_new_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/example.py"
            source.parent.mkdir()
            source.write_text("value = 1\n", encoding="utf-8")
            raw = root / "work/raw"
            raw.mkdir(parents=True)
            (raw / "ruff-correctness.stdout.json").write_text(
                json.dumps([{"filename": "src/example.py", "code": "F821"}]), encoding="utf-8"
            )
            for name in ("ruff-migration.stdout.json", "ruff-line-length.stdout.json"):
                (raw / name).write_text("[]\n", encoding="utf-8")
            (raw / "ruff-format.stdout.txt").write_text("", encoding="utf-8")
            (raw / "mypy.stdout.txt").write_text("", encoding="utf-8")
            (raw / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 80.0}}), encoding="utf-8")
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(_policy(_digest(source))), encoding="utf-8")
            run_path = root / "run.json"
            run_path.write_text(json.dumps(_run_receipt()), encoding="utf-8")

            result = validate_quality(
                repository_root=root,
                policy_path=policy_path,
                run_receipt_path=run_path,
                work_root=root / "work",
            )

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("new-quality-finding", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
