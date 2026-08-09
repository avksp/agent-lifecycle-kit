from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.launcher import launch_from_descriptor, launch_from_local_profile
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.redaction import redact_process_text
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.policy.risk_execution import derive_risk_execution_profile

ROOT = Path(__file__).resolve().parents[2]


class SecureAdapterLauncherTests(unittest.TestCase):
    def test_supported_profile_is_blocked_before_process_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "launched.txt"
            descriptor = _descriptor(argv=[sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('launched')"])

            receipt = launch_from_descriptor(
                descriptor=descriptor,
                session_id="session-1",
                launch_mode="interactive",
                process_env={"SAFE_TOKEN": "secret", "OTHER": "no"},
            )

            self.assertFalse(marker.exists())

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["shell"])
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertEqual(receipt["argv"], [])
        self.assertIn("adapter-generic-launch-disabled", {item["code"] for item in receipt["blockers"]})

    def test_wrapper_only_profile_blocks_native_launch(self) -> None:
        descriptor = _descriptor(status="WRAPPER_ONLY", reason="wrapper required")

        receipt = launch_from_descriptor(descriptor=descriptor, session_id="session-1", launch_mode="interactive")

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertIn("adapter-generic-launch-disabled", {item["code"] for item in receipt["blockers"]})

    def test_invalid_profile_returns_structured_blocker(self) -> None:
        receipt = launch_from_descriptor(
            descriptor={"adapterId": "codex", "managedLaunch": {"status": "SUPPORTED"}},
            session_id="session-1",
            launch_mode="interactive",
        )

        self.assertEqual(receipt["status"], "BLOCKED")
        codes = {item["code"] for item in receipt["blockers"]}
        self.assertIn("adapter-generic-launch-invalid-descriptor", codes)
        self.assertIn("adapter-generic-launch-disabled", codes)

    def test_local_profile_launch_requires_all_frozen_bindings_before_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = _write_local_profile(root)
            with patch("agent_lifecycle.adapter_sessions.launcher.run_process") as run_process:
                receipt = launch_from_local_profile(
                    profile_path=profile_path,
                    project_root=root,
                    operation="managedTask",
                    adapter_id="codex",
                    explicit_launch=True,
                )

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("local-launch-frozen-binding-missing", {item["code"] for item in receipt["blockers"]})
        run_process.assert_not_called()

    def test_local_profile_launch_validates_risk_and_calls_process_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = _write_local_profile(root)
            manifest = _manifest()
            state = _state(manifest)
            manifest_path = root / "plan.manifest.json"
            state_path = root / "state.json"
            lock_path = root / "plan.lock.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            state_path.write_text(json.dumps(state), encoding="utf-8")
            lock_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-plan-lock.v1",
                        "packageId": "package",
                        "planRevision": 1,
                        "manifestHash": canonical_digest(manifest),
                    }
                ),
                encoding="utf-8",
            )
            risk_profile = _risk_profile(manifest, state)
            result = {
                "status": "PASS",
                "exitCode": 0,
                "timedOut": False,
                "stdoutTail": "ready",
                "stdoutRedacted": False,
                "stderrTail": "",
                "stderrRedacted": False,
                "blockers": [],
            }
            with patch(
                "agent_lifecycle.adapter_sessions.launcher.run_process",
                return_value=result,
            ) as run_process:
                receipt = launch_from_local_profile(
                    profile_path=profile_path,
                    project_root=root,
                    operation="managedTask",
                    adapter_id="codex",
                    session_id="session-1",
                    explicit_launch=True,
                    state_path=state_path,
                    manifest_path=manifest_path,
                    lock_path=lock_path,
                    task_id="WS-01",
                    operation_id="route-op",
                    source_revision="source",
                    risk_profile=risk_profile,
                    process_env={"PATH": "/usr/bin", "SECRET": "not-forwarded"},
                )

        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(receipt["hostLaunchStarted"])
        self.assertEqual(receipt["env"]["includedNames"], ["PATH"])
        run_process.assert_called_once()
        self.assertNotIn("SECRET", run_process.call_args.kwargs["env"])

    def test_local_profile_launch_blocks_invalid_frozen_or_risk_lineage_without_process(self) -> None:
        for scenario in ("lock", "status", "task", "risk-lineage"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                profile_path = _write_local_profile(root)
                manifest = _manifest()
                state = _state(manifest)
                risk_profile = _risk_profile(manifest, state)
                lock_hash = canonical_digest(manifest)
                if scenario == "lock":
                    lock_hash = "0" * 64
                elif scenario == "status":
                    manifest["status"] = "DRAFT"
                    lock_hash = canonical_digest(manifest)
                elif scenario == "task":
                    state["tasks"] = []
                else:
                    risk_profile["sourceRevision"] = "different-source"

                manifest_path, state_path, lock_path = _write_launch_context(
                    root,
                    manifest=manifest,
                    state=state,
                    lock_hash=lock_hash,
                )
                with patch("agent_lifecycle.adapter_sessions.launcher.run_process") as run_process:
                    receipt = launch_from_local_profile(
                        profile_path=profile_path,
                        project_root=root,
                        operation="managedTask",
                        adapter_id="codex",
                        explicit_launch=True,
                        state_path=state_path,
                        manifest_path=manifest_path,
                        lock_path=lock_path,
                        task_id="WS-01",
                        operation_id="route-op",
                        source_revision="source",
                        risk_profile=risk_profile,
                    )

                self.assertEqual(receipt["status"], "BLOCKED")
                self.assertFalse(receipt["hostLaunchStarted"])
                run_process.assert_not_called()

    def test_process_start_failure_is_a_redacted_structured_result(self) -> None:
        result = run_process(
            ["definitely-not-an-installed-alk-test-command"],
            env={},
            timeout_seconds=1.0,
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["blockers"][0]["code"], "adapter-process-start-failed")
        self.assertIsNone(result["exitCode"])

    def test_process_redaction_covers_posix_and_windows_absolute_paths(self) -> None:
        redacted, changed = redact_process_text(
            "cache=/private/tmp/alk/run.json workspace=D:\\work\\private\\state.json"
        )

        self.assertTrue(changed)
        self.assertNotIn("/private/tmp", redacted)
        self.assertNotIn("D:\\work", redacted)


def _descriptor(*, argv: list[str] | None = None, status: str = "SUPPORTED", reason: str | None = None) -> dict:
    profile = {
        "status": status,
        "reason": reason,
        "shell": False,
        "timeoutSeconds": 5.0,
        "env": {"allow": ["SAFE_TOKEN"], "allowPatterns": [], "projectPolicyAllowed": False},
        "writesNativeConfig": False,
        "promptInjectionDefault": False,
    }
    if status == "SUPPORTED":
        profile["argvTemplates"] = {"interactive": argv or [sys.executable, "-c", ""], "managedTask": argv or [sys.executable, "-c", ""], "resume": argv or [sys.executable, "-c", ""]}
    return {"adapterId": "codex", "managedLaunch": profile}


def _write_local_profile(root: Path) -> Path:
    profile = json.loads(
        (ROOT / "tests/adapter_sessions/fixtures/local_launch_profiles/valid.json").read_text(encoding="utf-8")
    )
    profile["argvTemplate"] = ["--state", "{state_path}", "--task", "{task_id}"]
    path = root / ".alk/host-launch/codex.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def _manifest() -> dict:
    return {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package"},
        "specification": {
            "tier": "S2",
            "tierResolutionRequest": {
                "riskFlags": {"architecture": True, "security": True},
                "capabilityHints": ["architecture"],
            },
        },
        "workstreams": [{"id": "WS-01"}],
    }


def _state(manifest: dict) -> dict:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": canonical_digest(manifest),
        "sourceRevision": "source",
        "tasks": [{"id": "WS-01"}],
    }


def _risk_profile(manifest: dict, state: dict) -> dict:
    def load(path: str) -> dict:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))

    return derive_risk_execution_profile(
        manifest=manifest,
        state=state,
        task_id="WS-01",
        adapter_id="codex",
        adapter_host="codex",
        operation_id="route-op",
        source_revision="source",
        requested_risk="auto",
        risk_policy=load("profiles/risk-execution-policy.v1.json"),
        routing_profile=load("profiles/model-routing-profile.v1.json"),
        baseline_profile=load("profiles/lifecycle-baselines.v1.json"),
        host_profile=load("profiles/hosts/codex-live-profile.v1.json"),
    )


def _write_launch_context(
    root: Path,
    *,
    manifest: dict,
    state: dict,
    lock_hash: str,
) -> tuple[Path, Path, Path]:
    manifest_path = root / "plan.manifest.json"
    state_path = root / "state.json"
    lock_path = root / "plan.lock.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    lock_path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-plan-lock.v1",
                "packageId": "package",
                "planRevision": 1,
                "manifestHash": lock_hash,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, state_path, lock_path


if __name__ == "__main__":
    unittest.main()
