from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_stdlib_runtime_boundary import validate_stdlib_runtime_boundary


class StdlibRuntimeBoundaryTests(unittest.TestCase):
    def test_runtime_package_is_stdlib_only(self) -> None:
        result = validate_stdlib_runtime_boundary(Path("src/agent_lifecycle"))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["blockers"], [])

    def test_external_runtime_import_is_blocked_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__init__.py").write_text("import requests\n", encoding="utf-8")
            result = validate_stdlib_runtime_boundary(root)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["blockers"][0]["code"], "stdlib-runtime-import")


if __name__ == "__main__":
    unittest.main()
