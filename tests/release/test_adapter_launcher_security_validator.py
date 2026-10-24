from __future__ import annotations

import ast
import textwrap
import unittest
from pathlib import Path

from tools.release.validate_adapter_launcher_security import _boundary_blockers, _identity_and_redaction_blockers

ROOT = Path(__file__).resolve().parents[2]


class AdapterLauncherSecurityMarkerTests(unittest.TestCase):
    def test_named_security_sources_expose_identity_and_shared_redaction_markers(self) -> None:
        args = type(
            "Args",
            (),
            {
                "launcher": "src/agent_lifecycle/adapter_sessions/launcher.py",
                "profile": "src/agent_lifecycle/adapter_sessions/local_launch_profile.py",
                "qualification": "src/agent_lifecycle/adapter_sessions/qualification.py",
                "redaction": "src/agent_lifecycle/contracts/redaction.py",
            },
        )()
        for field in ("launcher", "profile", "qualification", "redaction"):
            setattr(args, field, str(ROOT / getattr(args, field)))
        expectations = {
            "launcher": ("launcher", ROOT / args.launcher),
            "profile": ("profile", ROOT / args.profile),
            "qualification": ("qualification", ROOT / args.qualification),
            "redaction": ("redaction", ROOT / args.redaction),
        }
        for _name, (category, path) in expectations.items():
            with self.subTest(category=category):
                self.assertEqual(
                    _identity_and_redaction_blockers(path, path.read_text(encoding="utf-8"), args),
                    [],
                )


class AdapterLauncherSyntaxTests(unittest.TestCase):
    def blockers(self, source: str, name: str = "fixture.py") -> set[str]:
        source = textwrap.dedent(source)
        ast.parse(source)  # Every negative case must exercise valid Python.
        return {row["code"] for row in _boundary_blockers(Path(name), source)}

    def test_shell_policy_uses_ast_and_requires_literal_false(self) -> None:
        for value in ("True", "(True)", "1", "enabled", "not False"):
            with self.subTest(value=value):
                source = f"import subprocess\nsubprocess.run([], shell = {value})"
                self.assertIn("adapter-launcher-shell-policy", self.blockers(source))
        self.assertEqual(self.blockers('# shell=True\ntext = "shell=True"\nf(shell = (False))'), set())

    def test_shell_unpacking_and_imported_shell_routes_are_refused(self) -> None:
        sources = (
            "import subprocess as child\nchild.run([], **{'shell': True})",
            "from subprocess import run as execute\nexecute([], **options)",
            "from os import system as execute\nexecute('command')",
            "import pty as terminal\nterminal.spawn(['command'])",
            "from pexpect import spawn as execute\nexecute('command')",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertIn("adapter-launcher-shell-policy", self.blockers(source))

    def test_import_aliases_and_from_imports_expose_process_routes(self) -> None:
        imports = (
            ("import subprocess", "subprocess.Popen"),
            ("import subprocess as child", "child.Popen"),
            ("from subprocess import Popen", "Popen"),
            ("from subprocess import Popen as spawn", "spawn"),
        )
        bodies = (
            "{call}([])",
            "def launch():\n    {call}([])",
            "class Launcher:\n    @classmethod\n    def launch(cls):\n        {call}([])",
            "def outer():\n    def inner():\n        {call}([])",
            "launch = lambda: {call}([])",
            "values = [{call}([]) for item in [1]]",
            "def launch(value={call}([])):\n    pass",
        )
        for statement, call in imports:
            for body in bodies:
                with self.subTest(statement=statement, body=body):
                    self.assertIn(
                        "adapter-unbounded-process-route", self.blockers(statement + "\n" + body.format(call=call))
                    )

    def test_local_imports_and_class_scopes(self) -> None:
        sources = (
            "def outer():\n    from subprocess import Popen as spawn\n    def inner():\n        spawn([])",
            "import subprocess as child\nclass Launcher:\n    child = None\n"
            "    def launch(self):\n        child.Popen([])",
            "class Launcher:\n    from subprocess import Popen as spawn\n    process = spawn([])",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertIn("adapter-unbounded-process-route", self.blockers(source))

    def test_lexically_shadowed_names_do_not_inherit_import_provenance(self) -> None:
        sources = (
            "import subprocess\ndef launch(subprocess):\n    subprocess.Popen([])",
            "from subprocess import Popen as spawn\ndef launch(spawn):\n    spawn([])",
            "from subprocess import Popen as spawn\ndef outer():\n    spawn = fake\n"
            "    def inner():\n        spawn([])",
            "import subprocess\nvalues = [subprocess.Popen([]) for subprocess in clients]",
            "import subprocess\nlaunch = lambda subprocess: subprocess.Popen([])",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(self.blockers(source), set())

    def test_generic_runner_aliases_cannot_borrow_allowed_parent(self) -> None:
        imports = (
            ("from agent_lifecycle.adapter_sessions.process import run_process as execute", "execute"),
            ("import agent_lifecycle.adapter_sessions.process as child", "child.run_process"),
        )
        for statement, call in imports:
            for body in (
                f"def launch_from_descriptor():\n    {call}([])",
                f"def launch_from_local_profile():\n    def nested():\n        {call}([])",
                f"class Launcher:\n    def launch_from_local_profile(self):\n        {call}([])",
            ):
                with self.subTest(statement=statement, body=body):
                    source = statement + "\n# adapter-generic-launch-disabled\n" + body
                    self.assertIn("adapter-generic-launch-process-route", self.blockers(source, "launcher.py"))
            safe = statement + f"\n# adapter-generic-launch-disabled\ndef launch_from_local_profile():\n    {call}([])"
            self.assertEqual(self.blockers(safe, "launcher.py"), set())

    def test_global_and_nonlocal_imports_remain_process_routes(self) -> None:
        sources = (
            "import subprocess as child\ndef launch():\n    global child\n    child.Popen([])",
            "def outer():\n    import subprocess as child\n    def launch():\n"
            "        nonlocal child\n        child.Popen([])",
            "import subprocess as child\ndef launch():\n    global child\n    child = fake\n    child.Popen([])",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertIn("adapter-unbounded-process-route", self.blockers(source))

    def test_bounded_git_aliases_keep_provenance(self) -> None:
        body = """
        # adapter-generic-launch-disabled
        def _git_bytes(root, args):
            return child.run(['git', *args], cwd=root, shell=False,
                             stdin=child.DEVNULL, stdout=child.PIPE,
                             stderr=child.PIPE, timeout=5, check=False)
        """
        source = "import subprocess as child\n" + textwrap.dedent(body)
        self.assertEqual(self.blockers(source, "launcher.py"), set())
        imported = source.replace("import subprocess as child", "from subprocess import run, PIPE, DEVNULL").replace(
            "child.", ""
        )
        self.assertEqual(self.blockers(imported, "launcher.py"), set())
        for replacement in ("child = fake", "from elsewhere import PIPE as PIPE"):
            changed = source + "\n" + replacement if "child" in replacement else imported + "\n" + replacement
            self.assertIn("adapter-git-identity-process-route", self.blockers(changed, "launcher.py"))

    def test_safe_bounded_sources_accept_subprocess_import_variants(self) -> None:
        base = ROOT / "src/agent_lifecycle/adapter_sessions"
        for name in ("process.py", "codex_exact_prompt.py", "codex_input_diagnostics.py"):
            source = (base / name).read_text()
            variants = (
                source.replace("import subprocess\n", "import subprocess as child\n").replace("subprocess.", "child."),
                source.replace("import subprocess\n", "from subprocess import Popen, PIPE, DEVNULL\n").replace(
                    "subprocess.", ""
                ),
            )
            for variant in variants:
                with self.subTest(name=name):
                    self.assertEqual(_boundary_blockers(base / name, variant), [])

    def test_bounded_exceptions_reject_rebound_dependencies(self) -> None:
        base = ROOT / "src/agent_lifecycle/adapter_sessions"
        cases = (
            ("process.py", "\n_finish_started_process = lambda *args, **kwargs: None\n"),
            ("process.py", "\nsubprocess = fake\n"),
            ("process.py", "\nsubprocess.PIPE = fake\n"),
            ("process.py", "\npopen_group_kwargs = fake\n"),
            ("codex_exact_prompt.py", "\n_require = lambda *args: None\n"),
            ("codex_input_diagnostics.py", "\ntime = fake\n"),
        )
        for name, suffix in cases:
            with self.subTest(name=name, suffix=suffix):
                blockers = _boundary_blockers(base / name, (base / name).read_text() + suffix)
                self.assertIn("adapter-unbounded-process-route", {row["code"] for row in blockers})

    def test_nested_function_cannot_supply_parent_bounds(self) -> None:
        source = """
        import subprocess
        def run_process(argv, env):
            process = subprocess.Popen(argv, shell=False, env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            def fake_bounds():
                max_input_bytes, max_output_bytes, timeout_seconds
                process.poll()
                process.wait()
                process.kill()
        """
        self.assertIn("adapter-unbounded-process-route", self.blockers(source, "process.py"))


if __name__ == "__main__":
    unittest.main()
