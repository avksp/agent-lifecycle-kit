from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools" / "release"
sys.path.insert(0, str(TOOLS_RELEASE))

import validate_repository_hygiene as hygiene  # noqa: E402


class RepositoryHygieneTests(unittest.TestCase):
    def test_policy_keeps_index_and_history_root_sets_distinct(self) -> None:
        policy = json.loads((ROOT / "policy/repository-hygiene.json").read_text(encoding="utf-8"))

        self.assertEqual(
            set(policy["indexForbiddenRoots"]),
            {".alk", ".claude", "dev", "out", "plans", "release", "tasks", "work"},
        )
        self.assertEqual(
            set(policy["historyForbiddenRoots"]),
            {".alk", ".claude", "dev", "out", "plans", "tasks", "work"},
        )

    def test_ci_and_release_workflows_use_the_intended_ref_scopes(self) -> None:
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn("validate_repository_hygiene.py", ci)
        self.assertNotIn("--all-refs", ci)
        self.assertIn("validate_repository_hygiene.py", release)
        self.assertIn("--all-refs", release)
        self.assertIn("fetch-depth: 0", ci)
        self.assertIn("fetch-depth: 0", release)

    def test_index_uses_exact_root_components(self) -> None:
        with _repository() as repo:
            for path in (
                ".alk/session.json",
                ".claude/settings.local.json",
                "dev/local.txt",
                "out/report.json",
                "plans/plan.md",
                "release/candidate/inventory.json",
                "tasks/task.md",
                "work/result.json",
                ".claude-plugin/plugin.json",
                "templates/tasks/example.md",
                "release-tooling.md",
            ):
                _write(repo.root / path, path)
            repo.commit("tracked roots")

            result = repo.validate(require_history=False)

            self.assertEqual(result["status"], "FAIL")
            roots = {item["root"] for item in result["findings"]}
            self.assertEqual(roots, {".alk", ".claude", "dev", "out", "plans", "release", "tasks", "work"})
            paths = {item["path"] for item in result["findings"]}
            self.assertNotIn(".claude-plugin/plugin.json", paths)
            self.assertNotIn("templates/tasks/example.md", paths)
            self.assertNotIn("release-tooling.md", paths)

    def test_deleted_host_local_path_fails_history_but_not_index(self) -> None:
        with _repository() as repo:
            _write(repo.root / ".claude/settings.local.json", "private")
            repo.commit("add local file")
            (repo.root / ".claude/settings.local.json").unlink()
            repo.git("add", "-A")
            repo.commit("delete local file")

            result = repo.validate(refs=["HEAD"], require_history=True)

            self.assertEqual(result["index"]["status"], "PASS")
            self.assertEqual(result["history"]["status"], "FAIL")
            self.assertIn(".claude/settings.local.json", {item["path"] for item in result["findings"]})

    def test_retained_release_history_and_near_misses_pass(self) -> None:
        with _repository() as repo:
            for path in (
                "release/notes/x.md",
                "templates/tasks/example.md",
                ".claude-plugin/plugin.json",
                "release-tooling.md",
            ):
                _write(repo.root / path, path)
            repo.commit("allowed history")
            for path in (
                "release/notes/x.md",
                "templates/tasks/example.md",
                ".claude-plugin/plugin.json",
                "release-tooling.md",
            ):
                (repo.root / path).unlink()
            repo.git("add", "-A")
            repo.commit("delete allowed history")

            result = repo.validate(refs=["HEAD"], require_history=True)

            self.assertEqual(result["status"], "PASS", result["blockers"])

    def test_mutating_history_policy_to_include_release_fails_discrimination(self) -> None:
        with _repository() as repo, tempfile.TemporaryDirectory() as tmp:
            _write(repo.root / "release/notes/x.md", "retained release history")
            repo.commit("release history")
            policy = json.loads((ROOT / "policy/repository-hygiene.json").read_text(encoding="utf-8"))
            policy["historyForbiddenRoots"].append("release")
            policy_path = Path(tmp) / "mutated-policy.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")

            result = repo.validate(refs=["HEAD"], require_history=True, policy_path=policy_path)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("release/notes/x.md", {item["path"] for item in result["findings"]})

    def test_all_refs_finds_prohibited_tag_only_object(self) -> None:
        with _repository() as repo:
            clean_commit = repo.commit("clean")
            repo.git("checkout", "-b", "temporary")
            _write(repo.root / ".alk/private.json", "private")
            repo.commit("tag-only private file")
            repo.git("tag", "prohibited-history")
            repo.git("checkout", "main")
            repo.git("branch", "-D", "temporary")
            self.assertEqual(repo.git("rev-parse", "HEAD").stdout.strip(), clean_commit)

            head_only = repo.validate(refs=["HEAD"], require_history=True)
            all_refs = repo.validate(refs=["HEAD"], all_refs=True, require_history=True)

            self.assertEqual(head_only["status"], "PASS", head_only["blockers"])
            self.assertEqual(all_refs["status"], "FAIL")
            finding = next(item for item in all_refs["findings"] if item["path"] == ".alk/private.json")
            self.assertEqual(finding["ref"], "refs/tags/prohibited-history")
            self.assertNotIn(str(repo.root), json.dumps(all_refs))

    def test_shallow_checkout_cannot_claim_complete_history(self) -> None:
        with _repository() as source:
            source.commit("source")
            with tempfile.TemporaryDirectory() as tmp:
                clone = Path(tmp) / "clone"
                subprocess.run(
                    ["git", "clone", "--depth", "1", source.root.as_uri(), str(clone)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    check=True,
                    timeout=30,
                    env=source.env,
                )
                result = hygiene.validate_repository_hygiene(
                    repository_root=clone,
                    policy_path=ROOT / "policy/repository-hygiene.json",
                    refs=["HEAD"],
                    all_refs=True,
                    require_history=True,
                )

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("repository-history-shallow-checkout", {item["code"] for item in result["blockers"]})

    def test_repository_ignore_rules_preserve_plugin_roots(self) -> None:
        with _repository() as repo:
            (repo.root / ".gitignore").write_text((ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")
            repo.commit("add repository ignore policy")
            ignored = [
                repo.git_result("check-ignore", "--no-index", "-q", path)
                for path in (
                    ".agent-lifecycle-authority/local.json",
                    ".alk/session.json",
                    ".claude/settings.local.json",
                    "dev/local",
                    "out/report",
                    "plans/plan.md",
                    "release/candidate/inventory.json",
                    "tasks/task.md",
                    "work/result.json",
                )
            ]
            allowed = repo.git_result("check-ignore", "--no-index", "-q", ".claude-plugin/plugin.json")

            self.assertTrue(all(process.returncode == 0 for process in ignored))
            self.assertEqual(allowed.returncode, 1)

    def test_legacy_history_records_are_checked_and_replace_objects_are_disabled(self) -> None:
        object_id = "a" * 40
        calls: list[list[str]] = []

        def fake_git(_root: Path, args: list[str], _budgets: hygiene.Budgets) -> hygiene.GitResult:
            calls.append(args)
            if args == ["ls-files", "-z"]:
                return hygiene.GitResult(0, b"", "")
            if args == ["rev-parse", "--is-shallow-repository"]:
                return hygiene.GitResult(0, b"false\n", "")
            if args[:3] == ["--no-replace-objects", "rev-parse", "--verify"]:
                return hygiene.GitResult(0, f"{object_id}\n".encode(), "")
            if args[:3] == ["--no-replace-objects", "rev-list", "-z"]:
                return hygiene.GitResult(0, f"{object_id} .claude/settings.local.json\0".encode(), "")
            raise AssertionError(args)

        with patch.object(hygiene, "_git", side_effect=fake_git):
            result = hygiene.validate_repository_hygiene(
                repository_root=ROOT,
                policy_path=ROOT / "policy/repository-hygiene.json",
                refs=["HEAD"],
                all_refs=False,
                require_history=True,
            )

        self.assertEqual(result["history"]["status"], "FAIL")
        self.assertIn(".claude/settings.local.json", {item["path"] for item in result["findings"]})
        self.assertTrue(any(args[:2] == ["--no-replace-objects", "rev-parse"] for args in calls))
        self.assertTrue(any(args[:2] == ["--no-replace-objects", "rev-list"] for args in calls))

    def test_unrecognized_history_output_and_absolute_git_errors_fail_closed_without_path_leak(self) -> None:
        object_id = "a" * 40
        private_path = "/" + "Users/private/repository"

        def malformed_git(_root: Path, args: list[str], _budgets: hygiene.Budgets) -> hygiene.GitResult:
            if args == ["ls-files", "-z"]:
                return hygiene.GitResult(0, b"", "")
            if args == ["rev-parse", "--is-shallow-repository"]:
                return hygiene.GitResult(0, b"false\n", "")
            if args[:3] == ["--no-replace-objects", "rev-parse", "--verify"]:
                return hygiene.GitResult(0, f"{object_id}\n".encode(), "")
            return hygiene.GitResult(0, b"not-an-object-record\0", "")

        with patch.object(hygiene, "_git", side_effect=malformed_git):
            malformed = hygiene.validate_repository_hygiene(
                repository_root=ROOT,
                policy_path=ROOT / "policy/repository-hygiene.json",
                refs=["HEAD"],
                all_refs=False,
                require_history=True,
            )
        with patch.object(
            hygiene,
            "_git",
            return_value=hygiene.GitResult(1, b"", hygiene._safe_text(f"fatal: {private_path}")),
        ):
            error = hygiene.validate_repository_hygiene(
                repository_root=ROOT,
                policy_path=ROOT / "policy/repository-hygiene.json",
                refs=[],
                all_refs=False,
                require_history=False,
            )
        with tempfile.TemporaryDirectory() as tmp:
            missing_policy_path = Path(tmp) / "private" / "missing-policy.json"
            missing_policy = hygiene.validate_repository_hygiene(
                repository_root=ROOT,
                policy_path=missing_policy_path,
                refs=[],
                all_refs=False,
                require_history=False,
            )

        self.assertIn("repository-history-output-invalid", {item["code"] for item in malformed["blockers"]})
        self.assertNotIn(private_path, json.dumps(error))
        self.assertNotIn(str(ROOT), json.dumps(error))
        self.assertNotIn(str(missing_policy_path), json.dumps(missing_policy))
        self.assertIn("<redacted>", json.dumps(missing_policy))

    def test_non_object_policy_fails_closed_with_structured_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = Path(tmp) / "invalid-policy.json"
            policy_path.write_text("[]", encoding="utf-8")

            result = hygiene.validate_repository_hygiene(
                repository_root=ROOT,
                policy_path=policy_path,
                refs=[],
                all_refs=False,
                require_history=False,
            )

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("invalid-repository-hygiene-policy", {item["code"] for item in result["blockers"]})
        self.assertNotIn(str(policy_path), json.dumps(result))


class _Repository:
    def __init__(self, root: Path, fixture_root: Path) -> None:
        self.root = root
        home = fixture_root / "fixture-home"
        hooks = fixture_root / "fixture-hooks"
        home.mkdir()
        hooks.mkdir()
        global_config = fixture_root / "fixture-global-config"
        global_config.write_text("", encoding="utf-8")
        self.env = {
            **os.environ,
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(global_config),
        }
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Repository Hygiene Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(hooks))
        _write(root / "README.md", "fixture")
        self.commit("initial")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.git_result(*args, check=True)

    def git_result(self, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def validate(
        self,
        *,
        refs: list[str] | None = None,
        all_refs: bool = False,
        require_history: bool = False,
        policy_path: Path | None = None,
    ) -> dict[str, object]:
        return hygiene.validate_repository_hygiene(
            repository_root=self.root,
            policy_path=policy_path or ROOT / "policy/repository-hygiene.json",
            refs=list(refs or []),
            all_refs=all_refs,
            require_history=require_history,
        )


class _repository:
    def __enter__(self) -> _Repository:
        self._temporary = tempfile.TemporaryDirectory()
        fixture_root = Path(self._temporary.name)
        repository_root = fixture_root / "repository"
        repository_root.mkdir()
        return _Repository(repository_root, fixture_root)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._temporary.cleanup()


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
