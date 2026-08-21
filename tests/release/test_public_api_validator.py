from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.release.validate_public_api import validate_public_api


class PublicApiValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]
        self.policy = self.root / "policy/python-public-api.json"
        self.english = self.root / "docs/reference/python-api.md"
        self.russian = self.root / "docs/ru/reference/python-api.md"

    def test_supported_facades_pass(self) -> None:
        result = validate_public_api(
            policy_path=self.policy,
            package_root=self.root / "src/agent_lifecycle",
            english_path=self.english,
            russian_path=self.russian,
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["blockers"], [])
        self.assertGreaterEqual(result["moduleCount"], 7)
        self.assertGreater(result["exportCount"], 100)

    def test_implicit_export_or_missing_documentation_is_blocked(self) -> None:
        policy = json.loads(self.policy.read_text(encoding="utf-8"))
        policy["modules"][0]["exports"].append("not_a_public_export")
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            result = validate_public_api(
                policy_path=policy_path,
                package_root=self.root / "src/agent_lifecycle",
                english_path=self.english,
                russian_path=self.russian,
            )

        self.assertEqual(result["status"], "FAIL")
        codes = {item["code"] for item in result["blockers"]}
        self.assertIn("public-api-export-inventory-mismatch", codes)
        self.assertIn("public-api-export-missing", codes)


if __name__ == "__main__":
    unittest.main()
