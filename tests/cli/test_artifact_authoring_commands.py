from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_lifecycle.cli.plan_lock_commands import prepare_freeze_candidate
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from tests.cli.helpers import _run_cli
from tests.cli.test_plan_verification_commands import _write_inputs


def _write_draft(root):
    manifest_path, lock_path, _ = _write_inputs(root)
    lock_path.unlink()
    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(status="DRAFT")
    manifest["package"].update(planArtifactRoot="plan", artifactRoot="work/fixture")
    manifest["planFiles"] = ["plan/acceptance-criteria.md", "plan/plan.manifest.json"]
    manifest["packageIntegrity"] = {
        "required": True,
        "lockSchemaVersion": "agent-plan-lock.v2",
        "allowedUnlistedFiles": ["plan.lock.json"],
    }
    manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
    return manifest_path, manifest


class ArtifactAuthoringCliTests(unittest.TestCase):
    def test_create_and_inspect_real_cli_preserve_canonical_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, out = root / "input.json", root / "new/artifact.json"
            source.write_text('{"z":2,\n "a":1}', encoding="utf-8")
            code, result = _run_cli(
                ["task", "artifact-create", "--kind", "json", "--input", str(source), "--out", str(out)]
            )
            self.assertEqual(code, 0, result)
            self.assertEqual(out.read_bytes(), b'{"a":1,"z":2}\n')
            self.assertFalse(result["authoritative"])
            code, display = _run_cli(["task", "artifact-inspect", "--input", str(out)])
            self.assertEqual(code, 0, display)
            self.assertEqual(json.loads(display["display"]), {"a": 1, "z": 2})
            code, _ = _run_cli(["task", "artifact-create", "--kind", "json", "--input", str(source), "--out", str(out)])
            self.assertEqual(code, 2)
            self.assertEqual(out.read_bytes(), b'{"a":1,"z":2}\n')

    def test_invalid_inputs_and_links_create_no_output_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, out = root / "input.json", root / "absent/artifact.json"
            for raw in (b'{"a":1,"a":2}', b'{"password":"unsafe"}', canonical_bytes({"note": "x" * 262144})):
                source.write_bytes(raw)
                code, _ = _run_cli(
                    ["task", "artifact-create", "--kind", "json", "--input", str(source), "--out", str(out)]
                )
                self.assertEqual(code, 2)
                self.assertFalse(out.parent.exists())
            source.write_bytes(b"{}")
            try:
                (root / "alias").symlink_to(root, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation is unavailable")
            code, _ = _run_cli(
                [
                    "task",
                    "artifact-create",
                    "--kind",
                    "json",
                    "--input",
                    str(source),
                    "--out",
                    str(root / "alias/x.json"),
                ]
            )
            self.assertEqual(code, 2)
            self.assertFalse((root / "x.json").exists())

    def test_freeze_prepare_real_cli_preserves_inputs_and_creates_no_review_or_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _ = _write_draft(root)
            original = {p.name: p.read_bytes() for p in path.parent.iterdir()}
            code, result = _run_cli(
                [
                    "plan",
                    "freeze-prepare",
                    "--manifest",
                    "plan/plan.manifest.json",
                    "--out",
                    "candidates/first",
                    "--repository-root",
                    str(root),
                ]
            )
            self.assertEqual(code, 0, result)
            receipt = json.loads((root / result["artifact"]["path"]).read_bytes())
            candidate = json.loads((root / result["candidateManifest"]).read_bytes())
            self.assertEqual(candidate["status"], "FROZEN")
            self.assertEqual(receipt["candidateDigest"], canonical_digest(candidate))
            self.assertFalse((root / receipt["pendingReviewPath"]).exists())
            self.assertFalse((root / "candidates/first/plan.lock.json").exists())
            self.assertFalse(receipt["authorityClaimed"])
            self.assertEqual(original, {p.name: p.read_bytes() for p in path.parent.iterdir()})
            for item in receipt["candidateFiles"]:
                self.assertEqual((root / item["path"]).stat().st_size, item["bytes"])

    def test_freeze_prepare_negatives_write_nothing(self):
        mutations = (
            lambda m: m["planFiles"].append(m["planFiles"][0]),
            lambda m: m["planFiles"].append("plan/missing.md"),
            lambda m: m["planFiles"].append("plan/../escape.md"),
            lambda m: m["package"].update(artifactRoot="plan"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, manifest = _write_draft(root)
                mutation(manifest)
                path.write_bytes(canonical_bytes(manifest) + b"\n")
                code, _ = _run_cli(
                    [
                        "plan",
                        "freeze-prepare",
                        "--manifest",
                        "plan/plan.manifest.json",
                        "--out",
                        "absent/candidate",
                        "--repository-root",
                        str(root),
                    ]
                )
                self.assertEqual(code, 2)
                self.assertFalse((root / "absent").exists())

    def test_freeze_candidate_collision_and_concurrent_creators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_draft(root)
            with self.assertRaises(LifecycleError):
                prepare_freeze_candidate(
                    manifest_path="plan/plan.manifest.json", output_path="plan/new", repository_root=root
                )
            self.assertFalse((root / "plan/new").exists())

            def prepare(_):
                try:
                    prepare_freeze_candidate(
                        manifest_path="plan/plan.manifest.json", output_path="candidate", repository_root=root
                    )
                    return True
                except (FileExistsError, LifecycleError):
                    return False

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(prepare, range(2)))
            self.assertEqual(sum(results), 1)
            self.assertTrue((root / "candidate/plan.manifest.json").is_file())

    def test_freeze_rejects_locked_old_review_oversize_and_forbidden_paths(self):
        for kind in ("locked", "old-review", "oversize", "forbidden"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, manifest = _write_draft(root)
                output = "absent/candidate"
                if kind == "locked":
                    (path.parent / "plan.lock.json").write_text("{}", encoding="utf-8")
                elif kind == "old-review":
                    manifest["planReview"] = {"report": "plan/review.json"}
                    manifest["planFiles"].append("plan/review.json")
                    (path.parent / "review.json").write_text("{}", encoding="utf-8")
                elif kind == "oversize":
                    manifest["planFiles"].append("plan/large.md")
                    (path.parent / "large.md").write_bytes(b"x" * 8_388_609)
                else:
                    manifest["forbiddenWrites"] = ["private"]
                    output = "private/candidate"
                path.write_bytes(canonical_bytes(manifest) + b"\n")
                code, _ = _run_cli(
                    [
                        "plan",
                        "freeze-prepare",
                        "--manifest",
                        "plan/plan.manifest.json",
                        "--out",
                        output,
                        "--repository-root",
                        str(root),
                    ]
                )
                self.assertEqual(code, 2)
                self.assertFalse((root / output.split("/")[0]).exists())

    def test_freeze_rejects_symlinked_input_or_destination(self):
        for linked in ("input", "output"):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, manifest = _write_draft(root)
                outside = root / "original.md"
                outside.write_text("unchanged", encoding="utf-8")
                try:
                    if linked == "input":
                        (path.parent / "alias.md").symlink_to(outside)
                        manifest["planFiles"].append("plan/alias.md")
                    else:
                        (root / "alias").symlink_to(root, target_is_directory=True)
                except OSError:
                    self.skipTest("Symlink creation is unavailable")
                path.write_bytes(canonical_bytes(manifest) + b"\n")
                output = "alias/candidate" if linked == "output" else "absent/candidate"
                code, _ = _run_cli(
                    [
                        "plan",
                        "freeze-prepare",
                        "--manifest",
                        "plan/plan.manifest.json",
                        "--out",
                        output,
                        "--repository-root",
                        str(root),
                    ]
                )
                self.assertEqual(code, 2)
                self.assertFalse((root / "candidate").exists())
                self.assertFalse((root / "absent").exists())
                self.assertEqual(outside.read_text(encoding="utf-8"), "unchanged")

    def test_compact_verify_requires_full_receipt_and_is_smaller(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _ = _write_draft(root)
            common = ["plan", "verify", "--manifest", str(path), "--repository-root", str(root)]
            code, _ = _run_cli([*common, "--compact"])
            self.assertEqual(code, 2)
            code, full = _run_cli(common)
            self.assertEqual(code, 0, full)
            out = root / "receipt.json"
            code, compact = _run_cli([*common, "--compact", "--out", str(out)])
            self.assertEqual(code, 0, compact)
            self.assertEqual(json.loads(out.read_bytes()), full)
            self.assertEqual(compact["artifact"]["digest"], canonical_digest(full))
            self.assertLess(len(canonical_bytes(compact)), len(canonical_bytes(full)))
