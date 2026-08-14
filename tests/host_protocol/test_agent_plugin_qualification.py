from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest, read_json_object
from agent_lifecycle.host_protocol.agent_plugin_qualification import (
    build_offline_qualification_receipt,
    run_agent_plugin_qualification_probe,
    validate_offline_receipt,
)


ROOT = Path(__file__).resolve().parents[2]
SKILLS = (
    "agent-first-planning",
    "agent-plan-to-workers",
    "agent-workflow-orchestrator",
    "audit-agent-plan",
    "audit-plan-implementation",
    "bug-forensics",
    "issue-to-spec",
)


def _profile() -> dict[str, object]:
    return read_json_object(ROOT / "adapters" / "codex" / "agent_plugin_profile.json")


def _make_tree(root: Path, *, package: bool = False) -> None:
    if package:
        root.mkdir(parents=True)
        (root / "plugin.json").write_text(json.dumps({"name": "agent-lifecycle-kit", "version": "1.68.0"}), encoding="utf-8")
    else:
        (root / ".codex-plugin").mkdir(parents=True)
        (root / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "agent-lifecycle-kit", "version": "1.68.0"}), encoding="utf-8")
    (root / "skills").mkdir()
    for skill in SKILLS:
        directory = root / "skills" / skill
        directory.mkdir()
        (directory / "SKILL.md").write_text("# skill\n", encoding="utf-8")


class AgentPluginQualificationHostProtocolTests(unittest.TestCase):
    def test_offline_receipt_contains_only_bounded_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            _make_tree(package, package=True)
            package_result = {"status": "PASS", "blockers": [], "skillNames": list(SKILLS)}
            receipt = build_offline_qualification_receipt(package_root=package, profile=_profile(), package_result=package_result)
            self.assertEqual(receipt["status"], "OFFLINE_VALIDATED")
            self.assertEqual(validate_offline_receipt(receipt)["status"], "PASS")
            self.assertFalse(receipt["rawOutputStored"])
            self.assertFalse(receipt["lifecycleCoverageClaimed"])
            self.assertNotIn(str(Path(tmp).resolve()), json.dumps(receipt))

    def test_explicit_probe_qualifies_a_matching_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            project = root / "project"
            _make_tree(package, package=True)
            _make_tree(project)

            def runner(argv: list[str], timeout: float) -> dict[str, object]:
                self.assertLessEqual(timeout, 10)
                return {"status": "PASS", "exitCode": 0, "timedOut": False, "stdout": "codex 1.68.0\n", "stderr": "", "blockers": []}

            receipt = run_agent_plugin_qualification_probe(
                package_root=package,
                project_root=project,
                profile=_profile(),
                host_bin="codex",
                command_runner=runner,
            )
            self.assertEqual(receipt["status"], "QUALIFIED")
            self.assertEqual(receipt["processCalls"], 2)

    def test_missing_client_is_unavailable_not_qualified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            project = root / "project"
            _make_tree(package)
            _make_tree(project)
            private_path = "/" + "Users/example/private"

            def runner(argv: list[str], timeout: float) -> dict[str, object]:
                return {
                    "status": "FAIL",
                    "exitCode": None,
                    "timedOut": False,
                    "stdout": "",
                    "stderr": f"{private_path}/cursor-agent: missing HOME",
                    "blockers": [{"code": "binary-not-found"}],
                }

            receipt = run_agent_plugin_qualification_probe(
                package_root=package,
                project_root=project,
                profile=_profile(),
                command_runner=runner,
            )
            self.assertEqual(receipt["status"], "UNAVAILABLE")
            self.assertIsNone(receipt["clientVersion"])
            self.assertNotIn(private_path, json.dumps(receipt))

    def test_client_version_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            project = root / "project"
            _make_tree(package, package=True)
            _make_tree(project)
            (project / ".codex-plugin/plugin.json").write_text('{"name":"agent-lifecycle-kit","version":"1.67.0"}', encoding="utf-8")

            def runner(argv: list[str], timeout: float) -> dict[str, object]:
                return {"status": "PASS", "exitCode": 0, "timedOut": False, "stdout": "codex 1.68.0\n", "stderr": "", "blockers": []}

            receipt = run_agent_plugin_qualification_probe(
                package_root=package,
                project_root=project,
                profile=_profile(),
                command_runner=runner,
            )
            self.assertEqual(receipt["status"], "BLOCKED")

    def test_missing_client_skill_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            project = root / "project"
            _make_tree(package, package=True)
            _make_tree(project)
            (project / "skills" / SKILLS[0] / "SKILL.md").unlink()

            def runner(argv: list[str], timeout: float) -> dict[str, object]:
                return {"status": "PASS", "exitCode": 0, "timedOut": False, "stdout": "codex 1.68.0\n", "stderr": "", "blockers": []}

            receipt = run_agent_plugin_qualification_probe(
                package_root=package,
                project_root=project,
                profile=_profile(),
                command_runner=runner,
            )
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertIn("client-skills-missing", {item["code"] for item in receipt["blockers"]})

    def test_unsupported_profile_returns_unavailable(self) -> None:
        profile = deepcopy(_profile())
        profile["qualification"]["status"] = "UNAVAILABLE"
        profile["profileDigest"] = canonical_digest({key: value for key, value in profile.items() if key != "profileDigest"})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            project = root / "project"
            _make_tree(package, package=True)
            _make_tree(project)
            receipt = run_agent_plugin_qualification_probe(
                package_root=package,
                project_root=project,
                profile=profile,
                command_runner=lambda argv, timeout: self.fail("unsupported profile must not start a process"),
            )
            self.assertEqual(receipt["status"], "UNAVAILABLE")

    def test_probe_reads_redacted_process_tails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            project = root / "project"
            _make_tree(package, package=True)
            _make_tree(project)

            def runner(argv: list[str], timeout: float) -> dict[str, object]:
                return {
                    "status": "PASS",
                    "exitCode": 0,
                    "timedOut": False,
                    "stdoutTail": "codex 1.68.0\n",
                    "stderrTail": "",
                    "blockers": [],
                }

            receipt = run_agent_plugin_qualification_probe(
                package_root=package,
                project_root=project,
                profile=_profile(),
                host_bin="codex",
                command_runner=runner,
            )
            self.assertEqual(receipt["status"], "QUALIFIED")
            self.assertEqual(receipt["clientVersion"], "codex 1.68.0")
            self.assertNotIn("stdoutTail", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
