from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.release.validate_declared_limit_semantics import LIMIT_SEMANTICS, validate_limit_semantics

ROOT = Path(__file__).resolve().parents[2]


class ArchitectureComplexityValidatorTests(unittest.TestCase):
    def test_validator_reports_file_function_and_symbol_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "agent_lifecycle"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            lines = ["def oversized():"] + ["    value = 1"] * 6 + ["    return value"]
            lines.extend(f"def symbol_{index}():\n    return {index}" for index in range(4))
            (package / "large.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
            evidence = Path(tmp) / "complexity.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_architecture_complexity.py"),
                    "--package-root",
                    str(package),
                    "--target-file-lines",
                    "5",
                    "--hard-file-lines",
                    "100",
                    "--target-function-lines",
                    "3",
                    "--hard-function-lines",
                    "5",
                    "--hard-symbols",
                    "2",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        codes = {item["code"] for item in payload["blockers"]}
        self.assertIn("architecture-file-target-exceeded", {row["code"] for row in payload["warnings"]})
        self.assertEqual(payload["targetFileConformance"], "EXCEEDED")
        self.assertIn("architecture-hard-function-limit-exceeded", codes)
        self.assertIn("architecture-hard-symbol-limit-exceeded", codes)
        self.assertEqual(LIMIT_SEMANTICS, payload["limitSemantics"])
        self.assertEqual("PASS", validate_limit_semantics(payload)["status"])

    def test_validator_passes_small_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "agent_lifecycle"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "small.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            evidence = Path(tmp) / "complexity.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_architecture_complexity.py"),
                    "--package-root",
                    str(package),
                    "--target-file-lines",
                    "800",
                    "--hard-file-lines",
                    "1200",
                    "--target-function-lines",
                    "80",
                    "--hard-function-lines",
                    "150",
                    "--hard-symbols",
                    "120",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["blockers"], [])

    def test_target_is_reported_and_hard_boundaries_still_refuse(self) -> None:
        cases = [
            ("file-800", "# line\n" * 800, 0, False, None),
            ("file-801", "# line\n" * 801, 0, True, None),
            ("file-1200", "# line\n" * 1200, 0, True, None),
            ("file-1201", "# line\n" * 1201, 1, True, "architecture-hard-file-limit-exceeded"),
            ("function-150", "def f():\n" + "    value = 1\n" * 148 + "    return value\n", 0, False, None),
            (
                "function-151",
                "def f():\n" + "    value = 1\n" * 149 + "    return value\n",
                1,
                False,
                "architecture-hard-function-limit-exceeded",
            ),
            ("symbols-80", "".join(f"def f{i}():\n    return {i}\n" for i in range(80)), 0, False, None),
            (
                "symbols-81",
                "".join(f"def f{i}():\n    return {i}\n" for i in range(81)),
                1,
                False,
                "architecture-hard-symbol-limit-exceeded",
            ),
        ]
        for label, source, exit_code, warning, code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                package = Path(tmp) / "agent_lifecycle"
                package.mkdir()
                (package / "__init__.py").write_text("", encoding="utf-8")
                (package / "fixture.py").write_text(source, encoding="utf-8")
                evidence = Path(tmp) / "complexity.json"
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "tools/release/validate_architecture_complexity.py"),
                        "--package-root",
                        str(package),
                        "--target-file-lines",
                        "800",
                        "--hard-file-lines",
                        "1200",
                        "--target-function-lines",
                        "80",
                        "--hard-function-lines",
                        "150",
                        "--hard-symbols",
                        "80",
                        "--evidence",
                        str(evidence),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                payload = json.loads(evidence.read_text(encoding="utf-8"))
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertEqual(
                    any(row["code"] == "architecture-file-target-exceeded" for row in payload["warnings"]), warning
                )
                self.assertEqual(
                    any(row["code"] == "architecture-function-target-exceeded" for row in payload["warnings"]),
                    label.startswith("function-"),
                )
                self.assertEqual(payload["targetFileConformance"], "EXCEEDED" if warning else "PASS")
                self.assertEqual(payload["hardLimitConformance"], "FAIL" if code else "PASS")
                self.assertEqual(payload["status"], "FAIL" if code else "PASS")
                self.assertEqual([row["code"] for row in payload["blockers"]], [code] if code else [])
                self.assertEqual("PASS", validate_limit_semantics(payload)["status"])


if __name__ == "__main__":
    unittest.main()


class BranchMetricContractTests(unittest.TestCase):
    def records(self, source):
        import ast

        from agent_lifecycle.quality.architecture_policy import function_branch_records

        return function_branch_records(ast.parse(source), "fixture.py")

    def policy(self, baseline=None):
        from agent_lifecycle.contracts import canonical_digest

        rows = baseline or []
        return {
            "branchLimit": 20,
            "branchBaseline": rows,
            "branchBaselineDigest": canonical_digest(rows),
            "branchExceptions": [],
        }

    def test_exact_nodes_boolean_operands_and_comprehension_filters(self):
        source = """def f(xs, ready):
    if ready and xs or ready:
        for x in xs:
            while x:
                x -= 1
    try:
        return [x if ready else 0 for x in xs if x and ready]
    except ValueError:
        return 0
"""
        self.assertEqual(10, self.records(source)[0]["score"])

    def test_match_case_alternatives_patterns_and_guards(self):
        source = """def f(x):
    match x:
        case 1 | 2:
            return 1
        case y if y > 3:
            return 2
        case _:
            return 3
"""
        self.assertEqual(4, self.records(source)[0]["score"])

    def test_nested_scopes_are_separate_and_docs_annotations_do_not_change_fingerprint(self):
        source = (
            "class C:\n    def f(self, x):\n        def g():\n            return 1 if x else 0\n        return g()\n"
        )
        records = self.records(source)
        self.assertEqual([("C.f", 0), ("C.f.g", 1)], [(r["name"], r["score"]) for r in records])
        before = self.records("def f(x):\n    return x\n")[0]
        after = self.records('def f(x: int) -> int:\n    """Documentation."""\n    # comment\n    return x\n')[0]
        self.assertEqual(before["fingerprint"], after["fingerprint"])
        self.assertNotEqual(before["fingerprint"], self.records("def f(x):\n    return x + 1\n")[0]["fingerprint"])

    def test_ratchet_rejects_new_changed_and_growing_debt_but_accepts_exact_or_twenty_percent_reduction(self):
        from agent_lifecycle.quality.architecture_policy import branch_findings

        old = self.records("def f(x):\n" + "    if x: x -= 1\n" * 30 + "    return x\n")[0]
        baseline = [{k: old[k] for k in ("path", "name", "score", "fingerprint")}]
        policy = self.policy(baseline)
        self.assertEqual([], branch_findings([old], policy))
        for count, allowed in ((31, False), (29, False), (24, True), (20, True)):
            row = self.records("def f(x):\n" + "    if x: x -= 1\n" * count + "    return x\n")[0]
            with self.subTest(count=count):
                self.assertEqual(allowed, not branch_findings([row], policy))
        self.assertTrue(branch_findings([old], self.policy()))
        policy["branchBaseline"].append({**baseline[0], "name": "new"})
        with self.assertRaises(ValueError):
            branch_findings([old], policy)

    def test_unreviewed_or_wildcard_exception_cannot_relax_gate(self):
        from agent_lifecycle.quality.architecture_policy import branch_findings

        policy = self.policy()
        policy["branchExceptions"] = [
            {"path": "*", "name": "f", "maxScore": 999, "reason": "", "owner": "", "tests": [], "review": ""}
        ]
        with self.assertRaises(ValueError):
            branch_findings([], policy)

    def test_nested_defaults_decorators_and_body_have_exactly_one_owner(self):
        expression = "x" + " or x" * 21
        for declaration in ("def", "async def"):
            source = (
                "def outer(x):\n"
                "    @decorate(x if x else fallback)\n"
                f"    {declaration} inner(value={expression}, *, enabled=x if x else False):\n"
                "        return value if enabled else None\n"
                "    return inner\n"
            )
            with self.subTest(declaration=declaration):
                records = self.records(source)
                self.assertEqual([("outer", 0), ("outer.inner", 24)], [(row["name"], row["score"]) for row in records])
                self.assertEqual(24, sum(row["score"] for row in records))

    def test_header_expression_threshold_cannot_disappear_or_be_double_counted(self):
        from agent_lifecycle.quality.architecture_policy import branch_findings

        expression = "x" + " or x" * 21
        sources = (
            f"def f(x):\n    return {expression}\n",
            f"def f(x):\n    def g(value={expression}):\n        return value\n    return g\n",
            f"def f(value={expression}):\n    return value\n",
            f"class C:\n    def f(self, *, value={expression}):\n        return value\n",
        )
        for source in sources:
            with self.subTest(source=source):
                rows = self.records(source)
                self.assertEqual(21, sum(row["score"] for row in rows))
                findings = branch_findings(rows, self.policy())
                self.assertEqual(1, len(findings))
                self.assertEqual(21, findings[0]["score"])


class ArchitecturePolicyIntegrationTests(unittest.TestCase):
    def test_production_limits_cannot_be_loosened_by_legacy_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "limits.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_architecture_complexity.py"),
                    "--package-root",
                    str(ROOT / "src/agent_lifecycle"),
                    "--hard-symbols",
                    "120",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("must agree", json.loads(evidence.read_text())["blockers"][0]["message"])

    def test_new_function_cannot_inherit_debt_by_name_or_large_cli_line_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample"
            root.mkdir()
            (root / "__init__.py").write_text("")
            (root / "fixture.py").write_text("def main(x):\n" + "    if x: x -= 1\n" * 21)
            evidence = Path(tmp) / "branches.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_architecture_complexity.py"),
                    "--package-root",
                    str(root),
                    "--hard-function-lines",
                    "1000",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            payload = json.loads(evidence.read_text())
            self.assertEqual(["architecture-branch-ratchet-violation"], [row["code"] for row in payload["blockers"]])
            self.assertEqual(21, payload["branches"][0]["score"])

    def test_cli_rejects_nested_default_kwdefault_and_decorator_threshold(self):
        expression = "x" + " or x" * 21
        definitions = (
            f"    def inner(value={expression}):\n        return value\n",
            f"    def inner(*, value={expression}):\n        return value\n",
            f"    @({expression})\n    def inner():\n        return x\n",
        )
        for definition in definitions:
            with self.subTest(definition=definition), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "sample"
                root.mkdir()
                (root / "__init__.py").write_text("")
                (root / "fixture.py").write_text("def outer(x):\n" + definition + "    return inner\n")
                evidence = Path(tmp) / "branches.json"
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "tools/release/validate_architecture_complexity.py"),
                        "--package-root",
                        str(root),
                        "--evidence",
                        str(evidence),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(1, result.returncode, result.stderr)
                payload = json.loads(evidence.read_text())
                self.assertEqual(
                    ["architecture-branch-ratchet-violation"], [row["code"] for row in payload["blockers"]]
                )
                self.assertEqual("outer.inner", payload["blockers"][0]["name"])
                self.assertEqual([0, 21], [row["score"] for row in payload["branches"]])


class SemanticFingerprintPortabilityTests(unittest.TestCase):
    def test_accepted_python312_golden_fingerprints(self):
        import ast

        from agent_lifecycle.quality.architecture_policy import semantic_fingerprint

        # Captured from the accepted implementation on actual Python 3.12.
        cases = (
            (
                ("def f(x):\n    return x\n"),
                "e5557f974d3c4016f6d67d07114392c94a3926e0457069ef35f5dfa6c10fe86f",
            ),
            (
                (
                    "@decorate(flag if enabled else fallback)\n"
                    "async def f(x=first or second, *, enabled=True):\n"
                    '    """Ignored documentation."""\n'
                    "    class Inner:\n"
                    "        def value(self):\n"
                    "            return None\n"
                    "    async def child(y=lambda z: z + 1):\n"
                    '        return f"{y!r}"\n'
                    "    if enabled:\n"
                    "        return [item for item in x if item]\n"
                    "    return await child()\n"
                ),
                "ed38f09846adee2f19b4a75563c8a2da027176e23969e866b4d2ccc1f363c30f",
            ),
            (
                (
                    "def f(value):\n"
                    "    match value:\n"
                    "        case [first, *rest] if first:\n"
                    '            return (None, True, b"x", 1.25, 2j, ..., rest[1:])\n'
                    '        case {"key": item, **rest}:\n'
                    "            try:\n"
                    '                return {**rest, "key": item}\n'
                    "            except ValueError as error:\n"
                    '                raise RuntimeError("failed") from error\n'
                    "        case _:\n"
                    "            return []\n"
                ),
                "9544a37ba41b44a9dc05c526419193532fefd527b10090863c1a7e0af8284b12",
            ),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                node = ast.parse(source).body[0]
                self.assertIsInstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                self.assertEqual(expected, semantic_fingerprint(node))

    def test_exact_accepted_dump_keeps_empty_lists_and_required_none(self):
        import ast

        from agent_lifecycle.quality.architecture_policy import _canonical_ast_dump

        node = ast.parse("def f(x):\n    return x\n").body[0]
        expected = (
            "FunctionDef(name='f', args=arguments(posonlyargs=[], args=[arg(arg='x')], kwonlyargs="
            "[], kw_defaults=[], defaults=[]), body=[Return(value=Name(id='x', ctx=Load()))], deco"
            "rator_list=[], type_params=[])"
        )
        self.assertEqual(expected, _canonical_ast_dump(node))
        self.assertEqual("Constant(value=None)", _canonical_ast_dump(ast.Constant(value=None)))

    def test_nonempty_type_parameters_are_retained_on_every_runtime(self):
        import ast

        from agent_lifecycle.quality.architecture_policy import _canonical_ast_dump, semantic_fingerprint

        node = ast.parse("def f(x):\n    return x\n").body[0]
        before = semantic_fingerprint(node)
        # Model populated type_params even on 3.11, whose parser lacks the field.
        node.type_params = [ast.Name(id="T", ctx=ast.Load())]
        self.assertIn("type_params=[Name(id='T', ctx=Load())]", _canonical_ast_dump(node))
        self.assertNotEqual(before, semantic_fingerprint(node))
        if hasattr(ast, "TypeVar"):
            first = ast.parse("def f[T](x):\n    return x\n").body[0]
            second = ast.parse("def f[U](x):\n    return x\n").body[0]
            self.assertNotEqual(semantic_fingerprint(first), semantic_fingerprint(second))

    def test_future_populated_fields_are_not_filtered_to_a_fixed_schema(self):
        import ast

        from agent_lifecycle.quality.architecture_policy import _canonical_ast_dump, semantic_fingerprint

        node = ast.parse("def f(x):\n    return x\n").body[0]
        before = semantic_fingerprint(node)
        node._fields = (*node._fields, "future_field")
        node.future_field = ast.Constant(value="first")
        first = semantic_fingerprint(node)
        self.assertNotEqual(before, first)
        self.assertIn("future_field=Constant(value='first')", _canonical_ast_dump(node))
        node.future_field = ast.Constant(value="second")
        self.assertNotEqual(first, semantic_fingerprint(node))

    def test_changed_body_defaults_decorators_nested_body_and_new_debt_still_refuse(self):
        import ast

        from agent_lifecycle.contracts import canonical_digest
        from agent_lifecycle.quality.architecture_policy import branch_findings, function_branch_records

        source = (
            "@decorate(flag)\ndef f(x=1, *, enabled=True):\n"
            + "    if enabled: x += 1\n" * 25
            + "    def nested():\n        return 1\n    return x\n"
        )
        original = function_branch_records(ast.parse(source), "fixture.py")[0]
        baseline = [{key: original[key] for key in ("path", "name", "score", "fingerprint")}]
        policy = {
            "branchLimit": 20,
            "branchBaseline": baseline,
            "branchBaselineDigest": canonical_digest(baseline),
            "branchExceptions": [],
        }
        self.assertEqual([], branch_findings([original], policy))
        for old, new in (
            ("return x", "return x + 1"),
            ("x=1", "x=2"),
            ("enabled=True", "enabled=False"),
            ("decorate(flag)", "decorate(other)"),
            ("return 1", "return 2"),
        ):
            changed = function_branch_records(ast.parse(source.replace(old, new)), "fixture.py")[0]
            with self.subTest(change=(old, new)):
                self.assertEqual(original["score"], changed["score"])
                self.assertNotEqual(original["fingerprint"], changed["fingerprint"])
                self.assertEqual("architecture-branch-ratchet-violation", branch_findings([changed], policy)[0]["code"])
        policy["branchBaseline"] = []
        policy["branchBaselineDigest"] = canonical_digest([])
        self.assertTrue(branch_findings([original], policy))

    def test_eager_import_flag_preserves_accepted_fingerprints(self):
        import ast

        from agent_lifecycle.quality.architecture_policy import semantic_fingerprint

        # Captured from the accepted pre-3.15-field canonical serializer.
        cases = (
            (
                "def f():\n    import os\n    return os.name\n",
                "2ad991006b44b6e0ee9fb623990844b83f5a9e5296a73b1bd4cf71ef46abd746",
            ),
            (
                "def f():\n    from os import path\n    return path\n",
                "c011421bac42f77c4d87ab05f9979182b3bbfea2420404672f856514013ecfae",
            ),
        )
        for source, expected in cases:
            node = ast.parse(source).body[0]
            statement = node.body[0]
            if "is_lazy" not in statement._fields:
                statement._fields = (*statement._fields, "is_lazy")
            statement.is_lazy = 0
            self.assertEqual(semantic_fingerprint(node), expected)
            for flag in (1, 2, False, 0.0, "0"):
                with self.subTest(source=source, flag=flag):
                    statement.is_lazy = flag
                    self.assertNotEqual(semantic_fingerprint(node), expected)

    def test_eager_default_normalization_keeps_unknown_and_nonimport_zero_fields(self):
        import ast

        from agent_lifecycle.quality.architecture_policy import _canonical_ast_dump, semantic_fingerprint

        node = ast.parse("def f():\n    import os\n    return os.name\n").body[0]
        statement = node.body[0]
        if "is_lazy" not in statement._fields:
            statement._fields = (*statement._fields, "is_lazy")
        statement.is_lazy = 0
        before = semantic_fingerprint(node)
        statement._fields = (*statement._fields, "future_field")
        statement.future_field = 0
        self.assertIn("future_field=0", _canonical_ast_dump(statement))
        self.assertNotEqual(semantic_fingerprint(node), before)
        other = ast.parse("def f():\n    return 1\n").body[0]
        before = semantic_fingerprint(other)
        other._fields = (*other._fields, "is_lazy")
        other.is_lazy = 0
        self.assertIn("is_lazy=0", _canonical_ast_dump(other))
        self.assertNotEqual(semantic_fingerprint(other), before)
