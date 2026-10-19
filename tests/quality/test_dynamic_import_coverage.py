"""Import coverage without executing the inspected package or registries."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.quality.dependency_impact import (
    build_dependency_graph,
    build_module_dependency_report,
    graph_from_report,
    strongly_connected_components,
    validate_module_dependency_report,
)


class DynamicImportCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "sample"
        self.root.mkdir()
        self.write("__init__.py", "raise RuntimeError('must never execute')\n")

    def write(self, name: str, source: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def report(self) -> dict:
        with patch("importlib.import_module", side_effect=AssertionError("must not import inspected code")):
            return build_module_dependency_report(self.root, repository_root=self.root.parent)

    def test_literal_dynamic_edge_and_reverse_import_expose_cycle(self) -> None:
        for importer in (
            "import importlib\nimportlib.import_module('sample.b')\n",
            "import importlib as il\nil.import_module('sample.b')\n",
            "from importlib import import_module as load\nload('sample.b')\n",
            "__import__('sample.b')\n",
            "__import__('sample.b', fromlist=[])\n",
            "import builtins as bi\nbi.__import__('sample.b', None, None, ())\n",
            "from builtins import __import__ as load\nload('sample.b', fromlist=())\n",
            "import builtins\nbuiltins.__import__('sample.b')\n",
            "import builtins as bi\nbi.__import__('sample.b')\n",
            "from builtins import __import__ as load\nload('sample.b')\n",
            "load = __import__\nload('sample.b')\n",
            "import builtins\nload = builtins.__import__\nload('sample.b')\n",
            "import builtins\ngetattr(builtins, '__import__')('sample.b')\n",
            "import builtins\nfirst = second\nsecond = builtins.__import__\nfirst('sample.b')\n",
            "import importlib\nload = importlib.import_module\nload('sample.b')\n",
            "import importlib\ngetattr(importlib, 'import_module')('sample.b')\n",
        ):
            with self.subTest(importer=importer):
                self.write("a.py", importer)
                self.write("b.py", "from . import a\n")
                report = self.report()
                self.assertTrue(report["graphComplete"])
                self.assertIn(["sample.a", "sample.b"], strongly_connected_components(graph_from_report(report)))

    def test_package_initializers_and_explicit_dynamic_relative_package(self) -> None:
        self.write("nested/__init__.py", "from . import leaf\nfrom .. import a\n")
        self.write("nested/leaf.py", "import importlib\nimportlib.import_module('.other', package=__package__)\n")
        self.write("nested/other.py", "")
        self.write("a.py", "")
        graph = graph_from_report(self.report())
        self.assertIn("sample.nested.leaf", graph["sample.nested"])
        self.assertIn("sample.a", graph["sample.nested"])
        self.assertNotIn("sample.leaf", graph["sample.nested"])
        self.assertIn("sample.nested.other", graph["sample.nested.leaf"])

    def test_unresolved_dynamic_edges_refuse_full_graph_even_when_static_edges_exist(self) -> None:
        self.write("b.py", "")
        sources = [
            "import importlib\nimport sample.b\nimportlib.import_module(input())\n",
            "from importlib import import_module\nimport_module(name)\n",
            "__import__(name)\n",
            "import builtins\nbuiltins.__import__(name)\n",
            "import builtins as bi\nbi.__import__(name)\n",
            "from builtins import __import__ as load\nload(name)\n",
            "import builtins\nload = builtins.__import__\nload(name)\n",
            "import builtins\ngetattr(builtins, attribute)('sample.b')\n",
            "import importlib\nimportlib.import_module('sample.missing')\n",
            "import importlib\nimportlib.import_module('')\n",
            "import importlib\nload = importlib.import_module\nload(name)\n",
            "import importlib\ngetattr(importlib, name)(name)\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.write("a.py", source)
                report = self.report()
                self.assertFalse(report["graphComplete"])
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["blockers"][0]["module"], "sample.a")
                self.assertEqual(validate_module_dependency_report(report)["status"], "FAIL")
                with self.assertRaises(LifecycleError):
                    graph_from_report(report)
                with self.assertRaises(LifecycleError):
                    build_dependency_graph(self.root, repository_root=self.root.parent)

    def test_builtin_aliases_keep_builtin_level_semantics(self) -> None:
        self.write("b.py", "")
        for setup, callee in (
            ("import builtins\n", "builtins.__import__"),
            ("import builtins as bi\n", "bi.__import__"),
            ("from builtins import __import__ as load\n", "load"),
            ("load = __import__\n", "load"),
        ):
            for arguments in ("'b', level=1", "'b', globals(), locals(), [], 1", "'.b'"):
                with self.subTest(callee=callee, arguments=arguments):
                    self.write("a.py", setup + f"{callee}({arguments})\n")
                    self.assertFalse(self.report()["graphComplete"])

    def test_builtin_fromlist_and_parameter_expansion_cannot_hide_submodule_cycle(self) -> None:
        self.write("b.py", "from . import a\n")
        for setup, callee in (
            ("", "__import__"),
            ("import builtins\n", "builtins.__import__"),
            ("import builtins as bi\n", "bi.__import__"),
            ("from builtins import __import__ as load\n", "load"),
            ("load = __import__\n", "load"),
        ):
            for arguments in (
                "'sample', fromlist=['b']",
                "'sample', None, None, ['b']",
                "'sample', fromlist=names",
                "'sample', fromlist=['*']",
                "'sample', *arguments",
                "'sample', **options",
            ):
                with self.subTest(callee=callee, arguments=arguments):
                    self.write("a.py", setup + f"{callee}({arguments})\n")
                    report = self.report()
                    self.assertFalse(report["graphComplete"])
                    self.assertEqual(report["status"], "FAIL")
                    self.assertTrue(report["blockers"])
                    with self.assertRaises(LifecycleError):
                        graph_from_report(report)

    def test_actual_cli_and_inspection_registries_are_parsed_without_eager_imports(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        with patch("importlib.import_module", side_effect=AssertionError("no eager imports")):
            report = build_module_dependency_report(repository / "src/agent_lifecycle", repository_root=repository)
        self.assertEqual(report["blockers"], [])
        graph = graph_from_report(report)
        self.assertIn("agent_lifecycle.cli.start", graph["agent_lifecycle.cli.dispatch"])
        self.assertIn("agent_lifecycle.cli.dispatch_lifecycle", graph["agent_lifecycle.cli.dispatch"])
        self.assertIn(
            "agent_lifecycle.host_protocol.inspection_codex", graph["agent_lifecycle.host_protocol.inspection"]
        )
        self.assertIn(
            "agent_lifecycle.host_protocol.inspection_gemini_cli", graph["agent_lifecycle.host_protocol.inspection"]
        )

    def test_changed_or_nonliteral_registry_does_not_get_a_completeness_exemption(self) -> None:
        self.write("cli/__init__.py", "")
        self.write(
            "cli/dispatch.py",
            "import importlib\ndef _lazy_call(module_name):\n    return importlib.import_module(module_name)\n",
        )
        for registry in (
            "COMMAND_DISPATCH = discover()\n",
            "COMMAND_DISPATCH = {'a': ('sample.a', 'run', False)}\nCOMMAND_DISPATCH = discover()\n",
            "COMMAND_DISPATCH = {'a': ('sample.a', 'run', False)}\nCOMMAND_DISPATCH.update(discover())\n",
        ):
            with self.subTest(registry=registry):
                self.write("cli/command_registry.py", registry)
                report = self.report()
                self.assertFalse(report["graphComplete"])
                self.assertEqual(report["blockers"][0]["module"], "sample.cli.dispatch")
