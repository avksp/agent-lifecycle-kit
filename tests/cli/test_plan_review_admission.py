from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import chdir
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_lifecycle.contracts import canonical_bytes, canonical_digest, sha256_hex
from tests.cli.helpers import _run_cli
from tests.cli.test_artifact_authoring_commands import _write_draft
from tests.cli.test_external_consumer_contract import PublicCliConsumer


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


class ReviewAdmissionFixture:
    def __init__(self, root: Path, executable: str | None = None):
        self.root = root
        self.consumer = PublicCliConsumer(executable, root) if executable else None
        self.source = self._init_git()
        draft, manifest = _write_draft(root)
        manifest["baseRevision"] = {"ref": "fixture", "sha": self.source}
        manifest["workstreams"][0]["contextRefs"] = ["reference.md"]
        (root / "reference.md").write_text("External disposable reference.\n", encoding="utf-8")
        write_json(draft, manifest)
        code, output = self.call(
            "plan", "freeze-prepare", "--manifest", "plan/plan.manifest.json", "--out", "candidate/plan"
        )
        if code != 0:
            raise AssertionError(output)
        self.manifest = output["candidateManifest"]
        self.preparation = output["artifact"]["path"]
        self.package = json.loads((root / self.manifest).read_bytes())
        self.packet = root / "packet.txt"
        self.packet.write_bytes(b"Disposable exact reviewer packet.\n")
        self.command = {
            "argv": [sys.executable, "-c", "from pathlib import Path; Path('unexpected-launch').touch()"],
            "cwd": ".",
            "shell": False,
        }
        self.packet_hash = sha256_hex(self.packet.read_bytes())
        self.request = {
            "schemaVersion": "agent-plan-review-preflight-request.v1",
            "sourceRevision": self.source,
            "packetSha256": self.packet_hash,
            "command": self.command,
            "budgetSnapshot": "budget.json",
        }
        write_json(root / "request.json", self.request)
        now = datetime.now(UTC)
        self.snapshot = {
            "schemaVersion": "agent-plan-review-budget-snapshot.v1",
            "previousObservedAt": (now - timedelta(seconds=10)).isoformat(),
            "observedAt": (now - timedelta(seconds=5)).isoformat(),
            "validUntil": (now + timedelta(minutes=20)).isoformat(),
            "previousGrossTokens": 79,
            "grossTokens": 80,
            "ceilingTokens": 100,
            "reserves": [{"operationId": "closeout", "tokens": 10}],
            "startedAbsentFromGross": [],
            "coldCacheBound": {
                "qualification": "DECLARED_LOCAL",
                "basis": "Deterministic test budget. No provider call.",
                "tokens": 10,
                "packetSha256": self.packet_hash,
                "commandDigest": canonical_digest(self.command),
            },
        }
        self.write_budget(self.snapshot)

    def _init_git(self) -> str:
        env = {**os.environ, "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"}
        git = ["git", "-C", str(self.root)]
        subprocess.run([*git, "init", "--quiet"], env=env, capture_output=True, check=True, timeout=10)
        subprocess.run(
            [
                *git,
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.test",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "--quiet",
                "-m",
                "Fixture",
            ],
            env=env,
            capture_output=True,
            check=True,
            timeout=10,
        )
        return subprocess.check_output([*git, "rev-parse", "HEAD"], text=True, timeout=10).strip()

    def write_budget(self, snapshot: dict) -> None:
        write_json(self.root / "budget.json", snapshot)

    def call(self, *argv: str) -> tuple[int, dict]:
        if self.consumer:
            return self.consumer.call(list(argv))
        with chdir(self.root):
            return _run_cli(list(argv))

    def preflight(self, out: str = "work/preflight.json") -> tuple[int, dict]:
        return self.call(
            "plan",
            "review-preflight",
            "--manifest",
            self.manifest,
            "--preparation",
            self.preparation,
            "--packet",
            "packet.txt",
            "--request",
            "request.json",
            "--out",
            out,
        )

    def write_review(self, packet_hash: str | None = None) -> str:
        report = self.package["planReview"]["report"]
        review = {
            "schemaVersion": "agent-plan-review.v1",
            "packageId": self.package["package"]["id"],
            "planRevision": self.package["planRevision"],
            "reviewedPlanHash": canonical_digest(self.package),
            "reviewId": "fixture-independent-review",
            "reviewer": {
                "id": "fixture-independent",
                "runId": "fixture-review",
                "surface": "test",
                "independent": True,
            },
            "fullReview": True,
            "verdict": "READY_TO_FREEZE",
            "findings": [],
        }
        if packet_hash is not None:
            review["reviewedPacketSha256"] = packet_hash
        write_json(self.root / report, review)
        return report

    def lock(self, *, strict: bool, packet_hash: str | None = None) -> tuple[int, dict]:
        report = self.write_review(packet_hash)
        args = ["plan", "lock-create", "--manifest", self.manifest, "--review", report]
        if strict:
            args += ["--review-preflight", "work/preflight.json"]
        return self.call(*args)

    def inventory(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.root)): sha256_hex(path.read_bytes())
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(self.root).parts
        }


class PlanReviewAdmissionTests(unittest.TestCase):
    executable: str | None = None
    scratch_root: Path | None = None

    def setUp(self) -> None:
        ws = self.enterContext(tempfile.TemporaryDirectory(dir=self.scratch_root))
        self.fixture = ReviewAdmissionFixture(Path(ws).resolve(), self.executable)

    def assert_budget_refusal(self, decision: str, reason: str) -> dict:
        f = self.fixture
        before = f.inventory()
        exit_code, actual = f.preflight()
        self.assertEqual(exit_code, 0, actual)
        self.assertEqual((actual["status"], actual["budgetDecision"]["reasonCode"]), (decision, reason))
        self.assertFalse(actual["modelCallsStarted"])
        self.assertEqual(before, f.inventory())
        return actual

    def test_exact_fit_keeps_external_reference_and_binds_lock(self) -> None:
        f = self.fixture
        status, receipt = f.preflight()
        self.assertEqual(status, 0, receipt)
        self.assertEqual(receipt["status"], "READY")
        self.assertEqual(receipt["budgetDecision"]["upperBoundTokens"], 100)
        self.assertEqual(receipt["commandDigest"], canonical_digest(f.command))
        self.assertEqual(f.package["workstreams"][0]["contextRefs"], ["reference.md"])
        self.assertFalse((f.root / "unexpected-launch").exists())
        code, lock = f.lock(strict=True, packet_hash=f.packet_hash)
        self.assertEqual(code, 0, lock)
        self.assertTrue(lock["filesystemVerified"])

    def test_started_work_above_lower_bound_refuses_exact_fit(self) -> None:
        f = self.fixture
        f.snapshot.update(grossTokens=90, startedAbsentFromGross=[{"operationId": "started", "unreportedTokens": 1}])
        f.write_budget(f.snapshot)
        receipt = self.assert_budget_refusal("INSUFFICIENT", "BUDGET_LOWER_BOUND_EXCEEDS_CEILING")
        self.assertEqual(receipt["budgetDecision"]["lowerBoundTokens"], 101)

    def test_retained_aik_reported_and_reserved_floor(self) -> None:
        f = self.fixture
        reserves = [{"operationId": "fixed", "tokens": 2044294}]
        reserves += [{"operationId": f"request-{i}", "tokens": 52000} for i in range(12)]
        f.snapshot.update(grossTokens=513353544, reserves=reserves, ceilingTokens=516000000)
        f.write_budget(f.snapshot)
        receipt = self.assert_budget_refusal("INSUFFICIENT", "BUDGET_LOWER_BOUND_EXCEEDS_CEILING")
        self.assertEqual(receipt["budgetDecision"]["lowerBoundTokens"], 516021838)

    def test_cache_loss_or_missing_upper_bound_defers(self) -> None:
        f = self.fixture
        f.snapshot["coldCacheBound"]["tokens"] = 11
        f.write_budget(f.snapshot)
        self.assert_budget_refusal("DEFERRED", "BUDGET_UPPER_BOUND_EXCEEDS_CEILING")
        f.snapshot["coldCacheBound"]["packetSha256"] = "a" * 64
        f.write_budget(f.snapshot)
        self.assert_budget_refusal("DEFERRED", "BUDGET_UPPER_BOUND_UNQUALIFIED")

    def test_order_freshness_and_duplicate_operations_defer(self) -> None:
        f = self.fixture
        for change in (
            {"previousObservedAt": f.snapshot["observedAt"]},
            {"previousObservedAt": f.snapshot["validUntil"]},
            {"observedAt": f.snapshot["validUntil"]},
            {"validUntil": f.snapshot["observedAt"]},
            {"reserves": [*f.snapshot["reserves"], *f.snapshot["reserves"]]},
        ):
            with self.subTest(change=change):
                f.write_budget({**f.snapshot, **change})
                self.assert_budget_refusal("DEFERRED", "BUDGET_OBSERVATION_INVALID")

    def test_unreadable_malformed_and_over_limit_snapshot_defer(self) -> None:
        f = self.fixture
        p = f.root / "budget.json"
        for content in (None, b"{", b"[]", b" " * (64 * 1024 + 1)):
            with self.subTest(content_size=len(content or b"")):
                if content is None:
                    p.unlink()
                else:
                    p.write_bytes(content)
                self.assert_budget_refusal("DEFERRED", "BUDGET_SNAPSHOT_UNAVAILABLE")

    def test_stale_candidate_or_invalid_checklist_refuse_without_writes(self) -> None:
        f = self.fixture
        manifest = f.root / f.manifest
        wrong = copy.deepcopy(f.package)
        wrong["package"]["planArtifactRoot"] = "stale/plan"
        write_json(manifest, wrong)
        before = f.inventory()
        code, receipt = f.preflight()
        self.assertEqual(code, 2, receipt)
        self.assertEqual(f.inventory(), before)
        write_json(manifest, f.package)
        acceptance = manifest.with_name("acceptance-criteria.md")
        acceptance.write_text("Invalid acceptance checklist.\n", encoding="utf-8")
        before = f.inventory()
        code, receipt = f.preflight()
        self.assertEqual((code, receipt["code"]), (2, "review-preflight-candidate-drift"))
        self.assertEqual(f.inventory(), before)

    def test_changed_packet_and_wrong_report_refuse_before_lock(self) -> None:
        f = self.fixture
        self.assertEqual(f.preflight()[1]["status"], "READY")
        code, receipt = f.lock(strict=True, packet_hash="f" * 64)
        self.assertEqual((code, receipt["code"]), (2, "review-preflight-report-mismatch"))
        f.packet.write_bytes(b"Different packet bytes.\n")
        code, receipt = f.lock(strict=True, packet_hash=f.packet_hash)
        self.assertEqual((code, receipt["code"]), (2, "review-preflight-subject-mismatch"))
        self.assertFalse((f.root / f.manifest).with_name("plan.lock.json").exists())

    def test_default_off_lock_needs_no_local_receipt(self) -> None:
        f = self.fixture
        code, receipt = f.lock(strict=False)
        self.assertEqual(code, 0, receipt)
        self.assertTrue(receipt["filesystemVerified"])
        self.assertFalse((f.root / "work/preflight.json").exists())

    def test_explicit_empty_or_missing_receipt_refuses_before_lock(self) -> None:
        f = self.fixture
        report = f.write_review(f.packet_hash)
        before = f.inventory()
        for supplied, expected in (("", "invalid-repo-path"), ("work/missing.json", "repository-file-missing")):
            with self.subTest(receipt=supplied):
                code, receipt = f.call(
                    "plan",
                    "lock-create",
                    "--manifest",
                    f.manifest,
                    "--review",
                    report,
                    "--review-preflight",
                    supplied,
                )
                self.assertEqual((code, receipt["code"]), (2, expected), receipt)
                self.assertEqual(f.inventory(), before)

    def test_first_preflight_with_existing_review_refuses_before_receipt(self) -> None:
        f = self.fixture
        f.write_review(f.packet_hash)
        before = f.inventory()
        code, receipt = f.preflight()
        self.assertEqual((code, receipt["code"]), (2, "review-preflight-review-exists"))
        self.assertEqual(f.inventory(), before)

    def test_dangling_review_link_prevents_first_preflight(self) -> None:
        f = self.fixture
        report = f.root / f.package["planReview"]["report"]
        missing = report.with_name("missing-review.json")
        try:
            report.symlink_to(missing)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows symlink fixture requires local link permission")
            raise
        target_before = report.readlink()
        before = f.inventory()
        code, receipt = f.preflight()
        self.assertEqual((code, receipt["code"]), (2, "review-preflight-review-exists"))
        self.assertEqual(f.inventory(), before)
        self.assertEqual(report.readlink(), target_before)
