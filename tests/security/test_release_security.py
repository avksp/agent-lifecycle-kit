from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

INTENTIONAL_PATH_FIXTURES = {
    "tests/context/test_checkpoints.py:" + "/" + "Volumes/",
}
sys.path.insert(0, str(ROOT / "src"))


class ReleaseSecurityTests(unittest.TestCase):
    def test_temporary_plan_artifacts_are_not_tracked(self) -> None:
        tracked_plan_paths = [path for path in _git_ls_files() if path == "plans" or path.startswith("plans/")]
        self.assertEqual(tracked_plan_paths, [])

    def test_tracked_text_files_do_not_contain_local_paths_or_secret_markers(self) -> None:
        from agent_lifecycle.contracts.redaction import contains_bare_secret_token

        forbidden = (
            "/" + "Volumes/",
            "/" + "Users/",
            "BEGIN " + "RSA PRIVATE KEY",
            "BEGIN " + "OPENSSH PRIVATE KEY",
            "BEGIN " + "PRIVATE KEY",
            "github" + "_pat_",
            "gh" + "p_",
            "xo" + "xb-",
        )
        offenders: list[str] = []
        for rel_path in _git_ls_files():
            path = ROOT / rel_path
            if not path.is_file():
                continue
            if _is_binary(path):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if contains_bare_secret_token(text):
                offenders.append(f"{rel_path}:bare-token")
            for marker in forbidden:
                if marker in text:
                    offenders.append(f"{rel_path}:{marker}")

        unexpected = set(offenders).difference(INTENTIONAL_PATH_FIXTURES)
        self.assertEqual(unexpected, set())

    def test_tracked_guard_refuses_each_bare_family_without_echoing_values(self) -> None:
        cases = [
            ("api", "sk-" + "A" * 20),
            ("project-api", "sk-proj-" + "B" * 20),
            ("jwt", "ey" + "J" + "A" * 8 + "." + "B" * 8 + "." + "C" * 8),
            ("github", "gh" + "o_" + "D" * 20),
            ("gitlab", "glpat-" + "E" * 20),
            ("npm", "npm_" + "F" * 20),
            ("payment", "rk_test_" + "G" * 16),
            ("hugging-face", "hf_" + "H" * 20),
            ("google", "AI" + "za" + "I" * 35),
            ("slack", "xox" + "a-" + "J" * 16),
            ("aws", "AK" + "IA" + "K" * 16),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(__name__ + ".ROOT", root), patch(__name__ + "._git_ls_files", return_value=["probe.py"]):
                for family, value in cases:
                    with self.subTest(family=family):
                        (root / "probe.py").write_text("# " + value, encoding="utf-8")
                        with self.assertRaises(AssertionError) as caught:
                            self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()
                        self.assertTrue(value not in str(caught.exception))

    def test_tracked_guard_keeps_legacy_rules_and_exact_path_exception(self) -> None:
        markers = [
            "/" + "Volumes/",
            "/" + "Users/",
            "BEGIN " + "RSA PRIVATE KEY",
            "BEGIN " + "OPENSSH PRIVATE KEY",
            "BEGIN " + "PRIVATE KEY",
            "github" + "_pat_",
            "gh" + "p_",
            "xo" + "xb-",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(__name__ + ".ROOT", root), patch(__name__ + "._git_ls_files", return_value=["probe.py"]):
                for index, value in enumerate(markers):
                    with self.subTest(marker=index):
                        (root / "probe.py").write_text(value, encoding="utf-8")
                        with self.assertRaises(AssertionError):
                            self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()
                (root / "probe.py").write_text("api_key = 'ordinary-placeholder'", encoding="utf-8")
                self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()
            for relative, allowed in (("tests/context/test_checkpoints.py", True), ("tests/context/other.py", False)):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("/" + "Volumes/", encoding="utf-8")
                with patch(__name__ + ".ROOT", root), patch(__name__ + "._git_ls_files", return_value=[relative]):
                    if allowed:
                        self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()
                    else:
                        with self.assertRaises(AssertionError):
                            self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()

    def test_verified_adapters_keep_host_bound_evidence_and_no_public_approval_claim(self) -> None:
        import json

        for path in sorted((ROOT / "adapters").glob("*/adapter.descriptor.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("maturity") != "VERIFIED":
                continue
            live_range = payload.get("liveTestedHostRange")
            self.assertIsInstance(live_range, dict, path.as_posix())
            self.assertFalse(live_range["productionPromotionClaimed"])
            self.assertFalse(live_range["publicDirectoryApprovalClaimed"])
            self.assertGreaterEqual(len(live_range["evidence"]), 3)
            self.assertTrue(payload.get("modelRouting", {}).get("liveVerified"))


def _git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=10,
    )
    return result.stdout.splitlines()


def _is_binary(path: Path) -> bool:
    data = path.read_bytes()
    return b"\0" in data


if __name__ == "__main__":
    unittest.main()
