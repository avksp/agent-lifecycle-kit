from __future__ import annotations

import json
import unittest
from pathlib import Path


class PythonApiDocumentationTests(unittest.TestCase):
    def test_english_and_russian_api_surfaces_match_policy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        policy = json.loads((root / "policy/python-public-api.json").read_text(encoding="utf-8"))
        english = (root / "docs/reference/python-api.md").read_text(encoding="utf-8")
        russian = (root / "docs/ru/reference/python-api.md").read_text(encoding="utf-8")

        self.assertIn("# Python API", english)
        self.assertIn("# Python API", russian)
        for module in policy["modules"]:
            module_name = module["module"]
            module_token = f"`{module_name}`"
            root_token = f"`{module_name}.__version__`"
            for document in (english, russian):
                self.assertTrue(module_token in document or root_token in document)
            for name in module["exports"]:
                name_token = f"`{name}`"
                self.assertTrue(name_token in english or f"`{module_name}.{name}`" in english)
                self.assertTrue(name_token in russian or f"`{module_name}.{name}`" in russian)

    def test_api_policy_is_machine_readable(self) -> None:
        root = Path(__file__).resolve().parents[2]
        policy = json.loads((root / "policy/python-public-api.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["schemaVersion"], "agent-python-public-api-policy.v1")
        self.assertTrue(policy["rules"]["rootExportsMustBeExplicit"])
        self.assertTrue(policy["rules"]["functionsRequireCompleteAnnotations"])


if __name__ == "__main__":
    unittest.main()
