from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.compiler import compile_small_model_packets, validate_small_model_output  # noqa: E402
from agent_lifecycle.contracts import canonical_digest, write_json_create  # noqa: E402
from agent_lifecycle.policy import build_adaptive_lifecycle_decision  # noqa: E402


class SmallModelPacketCompilerTests(unittest.TestCase):
    def test_compile_small_model_packets_writes_bounded_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _write_bundle(root)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                payload = compile_small_model_packets(
                    manifest,
                    context_profile_path=ROOT / "profiles/small-context-profile.v1.json",
                    adaptive_decision=_adaptive_decision(),
                    write=True,
                )
            finally:
                os.chdir(previous_cwd)

            packet_path = root / "plans/p/workflow/small-model-packets/WS-01.small-model-packet.json"
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], "agent-small-model-packet-compile-result.v1")
            self.assertTrue(packet_path.is_file())
            packet = payload["packets"][0]
            self.assertEqual(packet["schemaVersion"], "agent-small-model-task-packet.v1")
            self.assertEqual(packet["executionSurface"], "small-model")
            self.assertTrue(packet["writeScope"]["cannotExpand"])
            self.assertEqual(packet["context"]["window"], "4k-strict")
            self.assertTrue(packet["adaptivePolicy"]["smallModelPacketEligible"])

    def test_output_contract_validation_passes_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _write_bundle(root)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                payload = compile_small_model_packets(
                    manifest,
                    context_profile_path=ROOT / "profiles/small-context-profile.v1.json",
                )
            finally:
                os.chdir(previous_cwd)
        contract = payload["packets"][0]["requiredOutputContract"]
        good = {
            "schemaVersion": "agent-small-model-task-result.v1",
            "status": "PASS",
            "taskId": "WS-01",
            "changedFiles": ["src/example.py"],
            "validation": [{"command": "python -m unittest", "status": "PASS"}],
            "summary": "done",
            "blockers": [],
            "writeScopeDigest": contract["writeScopeDigest"],
            "outputContractDigest": contract["contractDigest"],
            "productionPromotionClaimed": False,
        }
        missing = dict(good)
        missing.pop("summary")
        outside = dict(good)
        outside["changedFiles"] = ["docs/outside.md"]

        self.assertEqual(validate_small_model_output(good, contract)["status"], "PASS")
        missing_validation = validate_small_model_output(missing, contract)
        outside_validation = validate_small_model_output(outside, contract)

        self.assertEqual(missing_validation["status"], "FAIL")
        self.assertIn("small-model-output-field-missing", {item["code"] for item in missing_validation["blockers"]})
        self.assertEqual(outside_validation["status"], "FAIL")
        self.assertIn("small-model-output-outside-write-scope", {item["code"] for item in outside_validation["blockers"]})

    def test_adaptive_strict_floor_blocks_small_model_packet_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _write_bundle(root)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                payload = compile_small_model_packets(
                    manifest,
                    context_profile_path=ROOT / "profiles/small-context-profile.v1.json",
                    adaptive_decision=_adaptive_decision(sddTier="S2", riskFlags=["security"]),
                )
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("small-model-quality-floor-blocked", {item["code"] for item in payload["blockers"]})


def _adaptive_decision(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schemaVersion": "agent-adaptive-lifecycle-policy-request.v1",
        "taskShape": "small-fix",
        "sddTier": "S1",
        "riskFlags": [],
        "requiredEvidence": [],
        "priorAttempts": 0,
        "contextTokens": 0,
        "resourceCaps": {"maxInvocations": 1},
        "budgetMode": "local",
        "automaticSelectionEnabled": False,
    }
    request.update(overrides)
    baselines = json.loads((ROOT / "profiles/lifecycle-baselines.v1.json").read_text(encoding="utf-8"))
    return build_adaptive_lifecycle_decision(request, baselines)


def _write_bundle(root: Path) -> Path:
    manifest = _manifest()
    digest = canonical_digest(manifest)
    write_json_create(
        root / "plans/p/.agent-plan/p/plan.lock.json",
        {"schemaVersion": "agent-plan-lock.v1", "manifestHash": digest, "planRevision": 1},
    )
    path = root / "plans/p/plan.manifest.json"
    write_json_create(path, manifest)
    return path


def _manifest() -> dict[str, object]:
    return {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {
            "id": "p",
            "artifactRoot": "plans/p",
            "planArtifactRoot": "plans/p/.agent-plan/p",
        },
        "specification": {"tier": "S1", "revision": 1, "artifact": "spec.json"},
        "readOnly": ["README.md"],
        "forbiddenWrites": ["docs/private"],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Compile small packet",
                "owner": "worker",
                "reviewer": "reviewer",
                "dependsOn": [],
                "writes": ["src"],
                "plannedItems": [{"id": "REQ-1", "description": "Do it"}],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
                "artifactPaths": {},
                "validationCommands": ["python -m unittest tests.compiler.test_small_model_packets -q"],
            }
        ],
        "acceptanceCriteria": [{"id": "AC-1", "evidenceIds": ["EV-1"]}],
    }


if __name__ == "__main__":
    unittest.main()
