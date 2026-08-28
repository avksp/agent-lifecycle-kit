from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

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
            for marker in forbidden:
                if marker in text:
                    offenders.append(f"{rel_path}:{marker}")

        unexpected = set(offenders).difference(INTENTIONAL_PATH_FIXTURES)
        self.assertEqual(unexpected, set())

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
    result = subprocess.run(["git", "ls-files"], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True)
    return result.stdout.splitlines()


def _is_binary(path: Path) -> bool:
    data = path.read_bytes()
    return b"\0" in data


if __name__ == "__main__":
    unittest.main()
