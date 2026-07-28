from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AdapterLayeringTests(unittest.TestCase):
    def test_core_does_not_import_adapter_projection_code(self) -> None:
        # NEG-R03-17 Layering Import Violation
        offenders: list[str] = []
        for path in (ROOT / "src/agent_lifecycle").rglob("*.py"):
            imports = _imported_modules(path)
            if any(name == "adapters" or name.startswith("adapters.") for name in imports):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_adapter_projection_does_not_reimplement_workflow_internals(self) -> None:
        offenders: list[str] = []
        adapter_root = ROOT / "adapters"
        for path in adapter_root.rglob("*.py"):
            imports = _imported_modules(path)
            if any(name.startswith("agent_lifecycle.workflow") for name in imports):
                offenders.append(path.relative_to(ROOT).as_posix())
        for path in adapter_root.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            if "agent_lifecycle.workflow" in text or "workflow/operation_kernel" in text:
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


if __name__ == "__main__":
    unittest.main()
