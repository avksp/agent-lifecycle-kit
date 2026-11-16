from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.review_mesh.assignments import source_from_manifest
from agent_lifecycle.review_mesh.contracts import build_review_mesh_profile, build_review_mesh_quorum_receipt
from agent_lifecycle.review_mesh.operator_templates import prepare_review_mesh_operator_packets
from tests.review_mesh.test_operator_templates import _handoff_fixture
from tests.review_mesh.test_remediation import config, policy


def _inventory(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()
    }


class PolicyInputRefusalTests(unittest.TestCase):
    def test_non_dictionary_quorum_policy_has_typed_refusal(self):
        profile = build_review_mesh_profile(independence_required=False)
        for invalid in (None, [], "", 1, True):
            with self.subTest(value=invalid), self.assertRaises(LifecycleError):
                build_review_mesh_quorum_receipt(
                    profile=profile,
                    mode=profile["defaultMode"],
                    subject={},
                    quorum_policy=invalid,
                    reviewer_count=1,
                )
        result = build_review_mesh_quorum_receipt(
            profile=profile,
            mode=profile["defaultMode"],
            subject={},
            quorum_policy={"minReviewers": 1},
            reviewer_count=1,
        )
        self.assertTrue(result["quorumSatisfied"])

    def test_source_manifest_policy_mismatch_refuses_symmetrically_before_output(self):
        selected = config(policy(mode="advisory", phases=["freeze"]))
        selected["required"] = False
        for source_on, manifest_on in ((True, False), (False, True)):
            with self.subTest(source=source_on, manifest=manifest_on), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                manifest, inventory = _handoff_fixture(root)
                if manifest_on:
                    manifest["reviewMesh"] = selected
                else:
                    manifest.pop("reviewMesh", None)
                raw = canonical_bytes(manifest) + b"\n"
                (root / "plan/plan.manifest.json").write_bytes(raw)
                for entry in inventory["inputs"]:
                    if entry["id"] == "AUTH":
                        entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                source = source_from_manifest(manifest)
                source["reviewMesh"] = selected if source_on else None
                before = _inventory(root)
                with self.assertRaises(LifecycleError) as caught:
                    prepare_review_mesh_operator_packets(
                        source=source,
                        template_id="leader-draft-review",
                        review_input=inventory,
                        authority_manifest=manifest,
                        repository_root=root,
                        out_dir=Path("prepared"),
                    )
                self.assertEqual(caught.exception.code, "review-remedy-source-mismatch")
                self.assertEqual(_inventory(root), before)
                self.assertFalse((root / "prepared").exists())

    def test_matching_legacy_policy_still_prepares(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory = _handoff_fixture(root)
            prepare_review_mesh_operator_packets(
                source=source_from_manifest(manifest),
                template_id="leader-draft-review",
                review_input=inventory,
                authority_manifest=manifest,
                repository_root=root,
                out_dir=Path("prepared"),
            )
            self.assertTrue((root / "prepared/reading-index.json").is_file())


if __name__ == "__main__":
    unittest.main()
