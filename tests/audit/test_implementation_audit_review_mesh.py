from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit import build_implementation_audit_report
from agent_lifecycle.contracts import write_json_create
from agent_lifecycle.review_mesh import build_review_mesh_profile, build_review_mesh_quorum_receipt

try:
    from .test_implementation_audit import _write_bundle, _write_result_review
except ImportError:
    from test_implementation_audit import _write_bundle, _write_result_review


class ImplementationAuditReviewMeshTests(unittest.TestCase):
    def test_required_review_mesh_quorum_is_checked_by_implementation_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            profile = _attach_required_review_mesh(root, bundle["statePath"], phase="implementation-audit")
            result_path, review_path = _write_result_review(root, bundle)
            receipt = _quorum_receipt(profile)
            write_json_create(root / "work/review-mesh/quorum.json", receipt)

            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
                review_mesh_quorum_paths=["work/review-mesh/quorum.json"],
            )

        self.assertEqual(report["status"], "PASS", report["blockers"])
        self.assertEqual(report["reviewMesh"]["validation"]["status"], "PASS")

    def test_required_review_mesh_quorum_missing_blocks_implementation_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            _attach_required_review_mesh(root, bundle["statePath"], phase="implementation-audit")
            result_path, review_path = _write_result_review(root, bundle)

            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("review-mesh-quorum-receipt-missing", {item["code"] for item in report["blockers"]})


def _attach_required_review_mesh(root: Path, state_path: Path, *, phase: str) -> dict:
    profile = build_review_mesh_profile(independence_required=False)
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    state["reviewMesh"] = {"required": True, "phases": [phase], "profileDigest": profile["profileDigest"]}
    state["tasks"][0]["reviewMesh"] = {"required": True, "phases": [phase], "profileDigest": profile["profileDigest"]}
    Path(state_path).write_text(json.dumps(state), encoding="utf-8")
    return profile


def _quorum_receipt(profile: dict) -> dict:
    return build_review_mesh_quorum_receipt(
        profile=profile,
        mode=profile["defaultMode"],
        subject={"taskId": "WS-01", "reviewMeshRequired": True},
        quorum_policy={"minReviewers": 1, "requiredRoles": []},
        reviewer_count=1,
    )


if __name__ == "__main__":
    unittest.main()
