from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402


class PolicyCommandTests(unittest.TestCase):
    def test_policy_tune_dry_run_writes_nothing_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "recommendation.json"
            report.write_text(json.dumps(_recommendation()), encoding="utf-8")
            before = sorted(path.name for path in root.iterdir())

            code, payload = _run_cli(["policy", "tune", "--report", str(report)])
            after = sorted(path.name for path in root.iterdir())

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-policy-tune-result.v1")
        self.assertEqual(payload["mode"], "dry-run")
        self.assertTrue(payload["proposal"]["applyAllowed"])
        self.assertEqual(before, after)

    def test_policy_tune_apply_requires_explicit_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "recommendation.json"
            report.write_text(json.dumps(_recommendation()), encoding="utf-8")

            code, payload = _run_cli(["policy", "tune", "--report", str(report), "--apply"])

        self.assertEqual(code, 2)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(payload["code"], "policy-apply-output-required")

    def test_policy_tune_apply_writes_policy_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "recommendation.json"
            output = root / "tuned-policy.json"
            report.write_text(json.dumps(_recommendation()), encoding="utf-8")

            code, payload = _run_cli(["policy", "tune", "--report", str(report), "--apply", "--output", str(output)])
            tuned = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["mode"], "apply")
        self.assertEqual(payload["applyResult"]["schemaVersion"], "agent-lifecycle-policy-apply-result.v1")
        self.assertEqual(tuned["schemaVersion"], "agent-lifecycle-tuned-policy.v1")
        self.assertFalse(tuned["productionPromotionClaimed"])

    def test_policy_tune_refuses_apply_when_regression_signal_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "recommendation.json"
            signal = root / "signal.json"
            output = root / "tuned-policy.json"
            report.write_text(json.dumps(_recommendation()), encoding="utf-8")
            signal.write_text(json.dumps({"type": "rollback", "count": 1, "severity": "HIGH"}), encoding="utf-8")

            code, payload = _run_cli(
                [
                    "policy",
                    "tune",
                    "--report",
                    str(report),
                    "--regression-signal",
                    str(signal),
                    "--apply",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "policy-apply-not-allowed")
        self.assertFalse(output.exists())

    def test_policy_tune_summary_fits_small_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "recommendation.json"
            summary = root / "policy-summary.json"
            packet = root / "task-packet.json"
            report.write_text(json.dumps(_recommendation()), encoding="utf-8")
            packet.write_text(json.dumps(_task_packet()), encoding="utf-8")

            code, payload = _run_cli(
                ["policy", "tune", "--report", str(report), "--summary-output", str(summary)]
            )
            context_code, context_payload = _run_cli(
                [
                    "context",
                    "check",
                    "--profile",
                    str(ROOT / "profiles/small-context-profile.v1.json"),
                    "--task-packet",
                    str(packet),
                    "--summary",
                    str(summary),
                    "--target-window",
                    "4k-strict",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(context_code, 0)
        self.assertEqual(context_payload["status"], "PASS")

    def test_policy_runtime_receipt_and_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject.json"
            evidence = root / "adapter-evidence.json"
            receipt = root / "runtime-policy-receipt.json"
            subject.write_text(json.dumps({"taskId": "WS-01", "capability": "network"}), encoding="utf-8")
            evidence.write_text(
                json.dumps(
                    {
                        "preExecutionEnforcement": True,
                        "decisionRecordedBeforeExecution": True,
                        "source": "host-protocol-envelope",
                    }
                ),
                encoding="utf-8",
            )

            code, payload = _run_cli(
                [
                    "policy",
                    "runtime-receipt",
                    "--policy-id",
                    "network-egress",
                    "--action",
                    "DENY",
                    "--subject",
                    str(subject),
                    "--adapter-evidence",
                    str(evidence),
                    "--enforcement-mode",
                    "enforced",
                    "--out",
                    str(receipt),
                ]
            )
            check_code, check_payload = _run_cli(["policy", "runtime-check", "--receipt", str(receipt)])

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-runtime-policy-receipt.v1")
        self.assertTrue(payload["enforcementClaimed"])
        self.assertEqual(check_code, 0)
        self.assertEqual(check_payload["schemaVersion"], "agent-runtime-policy-receipt-validation.v1")
        self.assertEqual(check_payload["status"], "PASS")


def _recommendation() -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-recommendation.v1",
        "status": "PASS",
        "taskShape": "small-fix",
        "currentMode": "strict",
        "recommendedMode": "light",
        "confidence": "HIGH",
        "advisoryOnly": True,
        "autoApply": False,
        "qualityFloor": "light",
        "qualityFloorPreserved": True,
        "warnings": [{"code": "pipeline-token-share-high"}],
        "reasons": ["recommendedMode=light"],
        "statistics": {
            "totals": {"pipelineCompliance": {"tokens": 3000}, "coordination": {"tokens": 500}},
            "ratios": {"pipelineTokenShare": 0.42},
        },
        "productionPromotionClaimed": False,
    }


def _task_packet() -> dict[str, object]:
    return {
        "schemaVersion": "agent-task-packet.v1",
        "plan": {"packageId": "release-1-6", "planRevision": 1, "planDigest": "0" * 64},
        "task": {
            "id": "WS16-03",
            "title": "Review policy proposal",
            "owner": "cli-docs-worker",
            "reviewer": "release-reviewer",
            "dependsOn": [],
            "required": True,
            "plannedItems": ["R16-07"],
            "acceptanceIds": ["AC16-CONTEXT"],
            "evidenceIds": ["EV16-CONTEXT"],
            "artifactPaths": {},
            "capabilityHints": [],
            "requiredTools": [],
            "executionPolicy": {},
        },
        "ownership": {"writes": ["src/agent_lifecycle/policy"], "readOnly": [], "forbiddenWrites": [], "leadOwned": []},
        "specification": {"tier": "S2", "revision": 1, "requirements": ["R16-07"], "traceDigest": "1" * 64},
        "context": {"refs": ["profiles/small-context-profile.v1.json"]},
        "validation": {"acceptanceIds": ["AC16-CONTEXT"], "evidenceIds": ["EV16-CONTEXT"]},
        "acceptance": [{"id": "AC16-CONTEXT", "statement": "policy summary fits"}],
    }


if __name__ == "__main__":
    unittest.main()
