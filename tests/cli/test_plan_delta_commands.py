from __future__ import annotations

import contextlib
import copy
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import canonical_digest
from tests.review import synthetic_case, synthetic_full_case, write_json


def _run(args: list[str]) -> tuple[int, dict]:
    output = StringIO()
    with contextlib.redirect_stdout(output):
        code = main(args)
    return code, json.loads(output.getvalue())


def _manifest(path: Path, revision: int, description: str) -> None:
    path.write_text(
        json.dumps(
            {
                "package": {"id": "sample"},
                "planRevision": revision,
                "status": "FROZEN",
                "baseRevision": {"ref": "main", "sha": "a" * 40},
                "specification": {"requirements": [{"id": "R1", "description": description}]},
                "workstreams": [],
                "acceptance": {"criteria": []},
                "validation": {},
            }
        ),
        encoding="utf-8",
    )


class PlanDeltaCliTests(unittest.TestCase):
    def test_selection_then_reviewed_lock_uses_actual_composite_consumer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            synthetic_case(root, git_repository=True)
            code, packet = self._packet(root, "--baseline", "plans/r1/review.json")
            self.assertEqual(code, 0)
            self.assertEqual(packet["mode"], "DELTA_ELIGIBLE")
            code, receipt = _run(
                [
                    "plan",
                    "lock-create",
                    "--repository-root",
                    str(root),
                    "--manifest",
                    "plans/r2/plan.manifest.json",
                    "--review",
                    "plans/r2/review.json",
                ]
            )
            self.assertEqual(code, 0, receipt)
            self.assertEqual(receipt["lockSchemaVersion"], "agent-plan-lock.v3")
            lock_bytes = (root / "plans/r2/plan.lock.json").read_bytes()
            (root / "runtime.py").write_text("authorized later implementation")
            code, refused = self._packet(root, "--baseline", "plans/r1/review.json")
            self.assertEqual(code, 0)
            self.assertEqual(refused["mode"], "FULL_REQUIRED")
            self.assertEqual((root / "plans/r2/plan.lock.json").read_bytes(), lock_bytes)

    def _packet(self, root: Path, *extra: str) -> tuple[int, dict]:
        return _run(
            [
                "plan",
                "review-packet",
                "--repository-root",
                str(root),
                "--manifest",
                "plans/r2/plan.manifest.json",
                *extra,
            ]
        )

    def test_review_packet_binds_real_git_and_creates_only_advisory_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_case(root, git_repository=True)
            code, packet = self._packet(
                root,
                "--baseline",
                "plans/r1/review.json",
                "--out",
                "packet.review-packet.json",
                "--subject-out",
                "packet.review-subject.json",
            )
            self.assertEqual(code, 0)
            self.assertEqual(packet["mode"], "DELTA_ELIGIBLE")
            subject = json.loads((root / "packet.review-subject.json").read_bytes())
            self.assertEqual(subject, case["delta"]["subject"])
            self.assertEqual(packet["candidateHash"], canonical_digest(case["manifest"]))
            self.assertFalse(packet["modelCallsStarted"])
            self.assertFalse((root / "plans/r2/plan.lock.json").exists())

    def test_default_full_packet_needs_no_baseline_or_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            synthetic_full_case(root)
            code, packet = _run(
                [
                    "plan",
                    "review-packet",
                    "--repository-root",
                    str(root),
                    "--manifest",
                    "plans/r1/plan.manifest.json",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(packet["mode"], "FULL")
            self.assertFalse(packet["modelCallsStarted"])

    def test_unsafe_inputs_refuse_without_any_output_or_authority_write(self):
        for mutation in ("runtime", "extra-runtime", "normative", "authority", "missing", "partial", "blocked"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                case = synthetic_case(root, git_repository=True)
                baseline = "plans/r1/review.json"
                if mutation in {"runtime", "normative", "authority"}:
                    name = {"runtime": "runtime.py", "normative": "plans/r1/plan.md", "authority": "authority.txt"}[
                        mutation
                    ]
                    (root / name).write_text("tampered")
                elif mutation == "extra-runtime":
                    (root / "extra.py").write_text("unreviewed")
                elif mutation == "missing":
                    (root / "plans/r1/plan.md").unlink()
                elif mutation == "partial":
                    baseline = "plans/r2/delta.json"
                else:
                    case["baseline"]["verdict"] = "BLOCKED"
                    write_json(root, baseline, case["baseline"])
                before = {
                    str(p.relative_to(root)): p.read_bytes()
                    for p in root.rglob("*")
                    if p.is_file() and ".git" not in p.parts
                }
                code, packet = self._packet(
                    root,
                    "--baseline",
                    baseline,
                    "--out",
                    "refused.review-packet.json",
                    "--subject-out",
                    "refused.review-subject.json",
                )
                self.assertEqual(code, 0)
                self.assertEqual(packet["mode"], "FULL_REQUIRED")
                self.assertFalse(packet["modelCallsStarted"])
                after = {
                    str(p.relative_to(root)): p.read_bytes()
                    for p in root.rglob("*")
                    if p.is_file() and ".git" not in p.parts
                }
                self.assertEqual(after, before)

    def test_outputs_cannot_target_plan_authority_or_protected_paths(self):
        for output in (
            "plans/r2/new.review-packet.json",
            ".alk/new.review-packet.json",
            "plan.lock.json",
            "plans/r2/plan.manifest.json",
        ):
            with self.subTest(output=output), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                synthetic_case(root, git_repository=True)
                code, _ = self._packet(root, "--baseline", "plans/r1/review.json", "--out", output)
                self.assertEqual(code, 2)
                self.assertFalse((root / "plans/r2/plan.lock.json").exists())

    def test_composite_baseline_has_physical_evidence_and_current_source_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_case(root, git_repository=True)
            manifest = copy.deepcopy(case["manifest"])
            manifest["planRevision"] = 3
            manifest["package"]["planArtifactRoot"] = "plans/r3"
            manifest["planFiles"] = [p.replace("r2/", "r3/") for p in manifest["planFiles"]]
            manifest["planReview"]["report"] = "plans/r3/review.json"
            seat = manifest["extensions"]["reviewPolicy"]["requiredSeats"][0]
            seat["reports"].append("plans/r3/delta.json")
            seat["current"] = "plans/r3/delta.json"
            write_json(root, "plans/r3/plan.manifest.json", manifest)
            (root / "plans/r3/plan.md").write_text("unchanged normative body")
            code, packet = _run(
                [
                    "plan",
                    "review-packet",
                    "--repository-root",
                    str(root),
                    "--manifest",
                    "plans/r3/plan.manifest.json",
                    "--baseline",
                    "plans/r2/review.json",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(packet["mode"], "DELTA_ELIGIBLE", packet)
            (root / "plans/r2/delta.json").write_text("{}")
            code, refused = _run(
                [
                    "plan",
                    "review-packet",
                    "--repository-root",
                    str(root),
                    "--manifest",
                    "plans/r3/plan.manifest.json",
                    "--baseline",
                    "plans/r2/review.json",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(refused["mode"], "FULL_REQUIRED")

    def test_delta_and_delta_check_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.json"
            after = root / "after.json"
            delta = root / "delta.json"
            _manifest(before, 1, "before")
            _manifest(after, 2, "after")
            code, payload = _run(["plan", "delta", "--before", str(before), "--after", str(after), "--out", str(delta)])
            self.assertEqual(code, 0)
            self.assertTrue(payload["reviewRequired"])
            code, checked = _run(["plan", "delta-check", "--delta", str(delta)])
            self.assertEqual(code, 0)
            self.assertEqual(checked["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
