from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "tools/release/validate_release_evidence_portability.py"


class ReleaseEvidencePortabilityValidatorTests(unittest.TestCase):
    def test_clean_evidence_directory_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            source.write_text(
                json.dumps({"status": "PASS", "path": "src/module.py", "outputIdentity": {"bytes": 0, "sha256": "0" * 64}}),
                encoding="utf-8",
            )
            evidence = root / "portability.json"

            subprocess.run(
                [sys.executable, str(VALIDATOR), "--evidence-dir", str(root), "--evidence", str(evidence)],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["artifactCount"], 1)

    def test_private_paths_credentials_and_raw_output_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_path = "/" + "Users/example/secret.txt"
            source = root / "source.json"
            source.write_text(
                json.dumps(
                    {
                        "path": private_path,
                        "authorization": "Bearer " + "x" * 24,
                        "token": "opaque-value",
                        "stderrTail": "raw process failure",
                    }
                ),
                encoding="utf-8",
            )
            evidence = root / "portability.json"

            result = subprocess.run(
                [sys.executable, str(VALIDATOR), "--evidence-dir", str(root), "--evidence", str(evidence)],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(
            {item["code"] for item in payload["blockers"]},
            {
                "release-evidence-private-absolute-path",
                "release-evidence-credential-like-value",
                "release-evidence-raw-process-output",
            },
        )
        self.assertEqual(
            sum(item["code"] == "release-evidence-credential-like-value" for item in payload["blockers"]),
            2,
        )

    def test_nested_platform_paths_and_compound_credentials_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            source.write_text(
                json.dumps(
                    {
                        "nested": [
                            {"windowsPath": r"C:\Users\example\secret.txt"},
                            {"linuxPath": "/root/.ssh/id_rsa"},
                            {"accessToken": "short"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            evidence = root / "portability.json"

            result = subprocess.run(
                [sys.executable, str(VALIDATOR), "--evidence-dir", str(root), "--evidence", str(evidence)],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(
            sum(item["code"] == "release-evidence-private-absolute-path" for item in payload["blockers"]),
            2,
        )
        self.assertIn(
            "$.nested[2].accessToken",
            {item.get("jsonPath") for item in payload["blockers"]},
        )

    def test_malformed_json_and_missing_directory_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            malformed_evidence = root / "malformed-portability.json"

            malformed_result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--evidence-dir",
                    str(root),
                    "--evidence",
                    str(malformed_evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            malformed_payload = json.loads(malformed_evidence.read_text(encoding="utf-8"))

            missing_evidence = root / "missing-portability.json"
            missing_result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--evidence-dir",
                    str(root / "absent"),
                    "--evidence",
                    str(missing_evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            missing_payload = json.loads(missing_evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(malformed_result.returncode, 0)
        self.assertIn("release-evidence-json-invalid", {item["code"] for item in malformed_payload["blockers"]})
        self.assertNotEqual(missing_result.returncode, 0)
        self.assertEqual(missing_payload["blockers"][0]["code"], "release-evidence-directory-missing")

    def test_private_key_marker_without_pem_dashes_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.json").write_text(
                json.dumps({"message": "BEGIN " + "PRIVATE KEY sensitive-material"}),
                encoding="utf-8",
            )
            evidence = root / "portability.json"

            result = subprocess.run(
                [sys.executable, str(VALIDATOR), "--evidence-dir", str(root), "--evidence", str(evidence)],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release-evidence-credential-like-value", {item["code"] for item in payload["blockers"]})

    def test_existing_output_receipt_is_the_only_excluded_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            evidence = root / "portability.json"
            evidence.write_text(json.dumps({"path": str(Path("/").joinpath("private", "old"))}), encoding="utf-8")

            subprocess.run(
                [sys.executable, str(VALIDATOR), "--evidence-dir", str(root), "--evidence", str(evidence)],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["artifactCount"], 1)

    def test_external_artifact_paths_preserve_relative_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "one" / "summary.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            (root / "two" / "summary.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            evidence = root / "portability.json"

            subprocess.run(
                [sys.executable, str(VALIDATOR), "--evidence-dir", str(root), "--evidence", str(evidence)],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(
            [item["path"] for item in payload["artifacts"]],
            ["external-evidence/one/summary.json", "external-evidence/two/summary.json"],
        )


if __name__ == "__main__":
    unittest.main()
