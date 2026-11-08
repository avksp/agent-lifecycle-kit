from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from agent_lifecycle.adapter_sessions import stage_launch
from agent_lifecycle.cli import main
from agent_lifecycle.cli.model_setup import _run_probe, apply_setup, discover_local_tools
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.model_routing.resolver import resolve_model_route
from agent_lifecycle.model_routing.setup import setup_proposal
from agent_lifecycle.resources import builtin_profile_path
from tests.adapter_sessions.test_stage_launch import select, write_fixture


def run_cli(root: Path, argv: list[str]) -> tuple[int, dict]:
    stream = io.StringIO()
    before = Path.cwd()
    try:
        os.chdir(root)
        with contextlib.redirect_stdout(stream):
            code = main(argv)
    finally:
        os.chdir(before)
    return code, json.loads(stream.getvalue())


class ModelSetupTests(unittest.TestCase):
    def test_selected_stage_risk_tightening_survives_policy_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile, _, _ = write_fixture(root)
            profile["stages"]["implementation"]["risk"] = "S2"
            profile_path = root / ".alk/project-profile.json"
            profile_path.write_text(json.dumps(profile))
            policies = stage_launch.stage_policy_inputs(root, profile, stage="implementation")
            request = stage_launch.stage_policy_request(
                {
                    "schemaVersion": "agent-lifecycle-model-route-request.v1",
                    "operationId": "UNIT_ONLY",
                    "phase": "task-implementation",
                    "sddTier": "S0",
                },
                policies,
            )
            self.assertEqual(request["sddTier"], "S2")
            selection = {
                "stage": "implementation",
                "projectProfilePath": ".alk/project-profile.json",
                "policyContext": policies,
            }
            self.assertEqual(stage_launch._reopen_stage_policies(root, selection)["requestedRisk"], "S2")
            host = json.loads((root / ".alk/host-launch/host.json").read_text())
            binding = host["bindings"]["strong-reasoning"]
            binding["allowedForTiers"] = ["S0"]
            host["bindings"] = {"budget": binding}
            routing = policies["routingProfile"]
            routing["phaseRules"]["task-implementation"] = "budget"
            with self.assertRaises(LifecycleError):
                resolve_model_route(request, routing, host_profile=host)
            profile["stages"]["implementation"]["risk"] = "S0"
            profile_path.write_text(json.dumps(profile))
            with self.assertRaises(LifecycleError):
                stage_launch._reopen_stage_policies(root, selection)

    def test_probe_help_success_cannot_mint_positive_public_availability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _profile, entry, _ = write_fixture(root)
            inspected = stage_launch.inspect_binding(root, entry)
            selection = {
                "stage": "implementation",
                "modelClass": "strong-reasoning",
                "selectedBindingDigest": inspected["bindingDigest"],
                "localProcessResult": {
                    "status": "PASS",
                    "processStarted": True,
                    "exitCode": 0,
                    "stdout": "Usage: codex exec --help",
                },
            }
            args = SimpleNamespace(
                operation_id="UNIT_ONLY",
                task="QPROBE",
                manifest="unused-unit-manifest.json",
                lock="unused-unit-lock.json",
                source_revision="UNIT_ONLY",
                expected_revision=1,
                portable=True,
            )
            marker = root / ".alk/host-launch/probe-UNIT_ONLY.json"
            marker.write_text('{"status":"DISPATCH_PENDING","test":"UNIT_ONLY"}')
            launch = {"status": "PASS", "hostLaunchStarted": True, "receiptDigest": "f" * 64}
            with patch("agent_lifecycle.cli.model_setup.launch_from_local_profile", return_value=launch):
                result = _run_probe(args, root, inspected, selection, root / "state.json", {"attempt": 1}, {}, marker)
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertEqual(result["launch"]["status"], "PASS")  # Preserve the physical process result.
            self.assertTrue(marker.exists())
            code, view = run_cli(
                root,
                [
                    "model",
                    "availability",
                    "--binding",
                    "primary",
                    "--project-profile",
                    ".alk/project-profile.json",
                    "--portable",
                ],
            )
            self.assertEqual(code, 0)
            self.assertEqual(view["status"], "UNAVAILABLE")
            self.assertEqual(view["qualityQualification"], "UNAVAILABLE")

    def test_explicit_project_policy_context_and_changed_or_missing_policy_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile, _, _ = write_fixture(root)
            policies = root / "policies"
            policies.mkdir()
            references = {
                "routingProfile": "model-routing-profile.v1.json",
                "riskPolicy": "risk-execution-policy.v1.json",
                "baselineProfile": "lifecycle-baselines.v1.json",
            }
            for name, builtin in references.items():
                payload = json.loads(Path(builtin_profile_path(builtin)).read_text())
                if name == "routingProfile":
                    payload["phaseRules"]["task-implementation"] = "budget"
                (policies / builtin).write_text(json.dumps(payload))
                profile["policies"][name] = "policies/" + builtin
            (root / ".alk/project-profile.json").write_text(json.dumps(profile))
            request = {
                "schemaVersion": "agent-lifecycle-model-route-request.v1",
                "operationId": "unit-policy",
                "phase": "task-implementation",
                "sddTier": "S0",
            }
            (root / "request.json").write_text(json.dumps(request))
            with (
                patch(
                    "agent_lifecycle.cli.model_setup.stage_launch.select_stage_binding",
                    return_value={"status": "BLOCKED"},
                ) as selected,
                patch("agent_lifecycle.cli.model_setup.launch_from_local_profile") as launch,
            ):
                code, _ = run_cli(
                    root,
                    [
                        "model",
                        "explain",
                        "--stage",
                        "implementation",
                        "--project-profile",
                        ".alk/project-profile.json",
                        "--request",
                        str(root / "request.json"),
                    ],
                )
            self.assertEqual(code, 0)
            self.assertEqual(selected.call_args.kwargs["request"]["sddTier"], "S0")
            self.assertEqual(
                selected.call_args.kwargs["routing_profile"]["phaseRules"]["task-implementation"], "budget"
            )
            launch.assert_not_called()
            context = stage_launch.stage_policy_inputs(root, profile)
            profile["defaultRisk"] = "S2"
            strict = stage_launch.stage_policy_inputs(root, profile)
            self.assertEqual(stage_launch.stage_policy_request(request, strict)["sddTier"], "S2")
            profile["defaultRisk"] = "auto"
            selection = select(root, profile, explicit_probe=True)
            selection["policyContext"] = context
            selection["pins"].update(context["pins"])
            changed = policies / "model-routing-profile.v1.json"
            changed.write_text("{}")
            with self.assertRaises(LifecycleError):
                stage_launch._reopen_stage_policies(root, selection)
            changed.unlink()
            with self.assertRaises((LifecycleError, FileNotFoundError)):
                stage_launch.stage_policy_inputs(root, profile)

    def test_probe_uses_current_manifest_tier_and_preserves_budget_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write_fixture(root)
            # Synthetic UNIT_ONLY lineage; selection is stopped before any host call.
            raw = b'{"fixture":"UNIT_ONLY"}\n'
            (root / "authorization.json").write_bytes(raw)
            state = {
                "stateRevision": 1,
                "sourceRevision": "unit-source",
                "authorization": {
                    "granted": True,
                    "expiresAt": "2099-01-01T00:00:00Z",
                    "authorizationReceipt": {
                        "path": "authorization.json",
                        "sha256": canonical_digest(json.loads(raw)),
                        "bytes": len(canonical_bytes(json.loads(raw)) + b"\n"),
                    },
                },
                "tasks": [{"id": "WS-01", "status": "RUNNING", "attempt": 1}],
            }
            (root / "state.json").write_text(json.dumps(state))
            argv = [
                "model",
                "availability",
                "--binding",
                "primary",
                "--project-profile",
                ".alk/project-profile.json",
                "--probe",
                "--authorization-receipt",
                str(root / "authorization.json"),
                "--state",
                str(root / "state.json"),
                "--manifest",
                str(root / "manifest.json"),
                "--lock",
                str(root / "lock.json"),
                "--task",
                "WS-01",
                "--operation-id",
                "unit-probe",
                "--expected-revision",
                "1",
                "--source-revision",
                "unit-source",
                "--max-invocations",
                "1",
                "--max-wall-seconds",
                "1",
                "--max-output-bytes",
                "1024",
            ]
            requests = {}
            for tier in ("S0", "S1", "S2"):
                (root / "manifest.json").write_text(json.dumps({"specification": {"tier": tier}}))
                with (
                    patch(
                        "agent_lifecycle.cli.model_setup.stage_launch.select_stage_binding",
                        return_value={"status": "BLOCKED", "reasonCodes": ["UNIT_ONLY_SELECTION_STOP"]},
                    ) as selected,
                    patch("agent_lifecycle.cli.model_setup.launch_from_local_profile") as launch,
                ):
                    code, _ = run_cli(root, argv)
                self.assertEqual(code, 0)
                requests[tier] = selected.call_args.kwargs["request"]
                self.assertEqual(requests[tier]["sddTier"], tier)
                launch.assert_not_called()
            for mutation in ("document", "raw-digest", "bytes", "foreign-path"):
                changed_state = json.loads(json.dumps(state))
                changed_argv = list(argv)
                (root / "authorization.json").write_bytes(raw)
                if mutation == "document":
                    (root / "authorization.json").write_text('{"fixture":"foreign"}')
                elif mutation == "raw-digest":
                    changed_state["authorization"]["authorizationReceipt"]["sha256"] = hashlib.sha256(raw).hexdigest()
                elif mutation == "bytes":
                    changed_state["authorization"]["authorizationReceipt"]["bytes"] += 1
                else:
                    (root / "foreign-authorization.json").write_bytes(raw)
                    changed_argv[changed_argv.index("--authorization-receipt") + 1] = str(
                        root / "foreign-authorization.json"
                    )
                (root / "state.json").write_text(json.dumps(changed_state))
                with (
                    patch("agent_lifecycle.cli.model_setup.stage_launch.select_stage_binding") as selected,
                    patch("agent_lifecycle.cli.model_setup.launch_from_local_profile") as launch,
                ):
                    code, refused = run_cli(root, changed_argv)
                self.assertEqual(code, 2, refused)
                self.assertEqual(refused["code"], "model-probe-authorization-mismatch")
                selected.assert_not_called()
                launch.assert_not_called()
            host = json.loads((root / ".alk/host-launch/host.json").read_text())
            binding = host["bindings"]["strong-reasoning"]
            binding["allowedForTiers"] = ["S0"]
            host["bindings"] = {"budget": binding}
            routing = json.loads(Path(builtin_profile_path("model-routing-profile.v1.json")).read_text())
            with self.assertRaises(LifecycleError):
                resolve_model_route(requests["S0"], routing, host_profile=host)
            trusted_routing = {**routing, "phaseRules": {**routing["phaseRules"], "task-implementation": "budget"}}
            self.assertEqual(
                resolve_model_route(requests["S0"], trusted_routing, host_profile=host)["modelClass"], "budget"
            )
            with self.assertRaises(LifecycleError):
                resolve_model_route(requests["S2"], trusted_routing, host_profile=host)

    def test_noninteractive_missing_input_is_structured_and_no_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("agent_lifecycle.cli.model_setup.run_process") as process:
            code, result = run_cli(Path(tmp), ["model", "setup", "--manual"])
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "MISSING_INPUT")
            self.assertEqual(result["requiredFields"], ["projectProfile", "registry"])
            process.assert_not_called()
            self.assertFalse((Path(tmp) / ".alk").exists())

    def test_manual_dry_run_is_read_only_and_portable_excludes_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, _, registry = write_fixture(root)
            source = root / "input.json"
            source.write_text(json.dumps({"projectProfile": profile, "registry": registry}))
            before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            code, result = run_cli(root, ["model", "setup", "--manual", "--input", str(source), "--portable"])
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "READY")
            self.assertNotIn("private-model", json.dumps(result))
            self.assertEqual(before, {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()})

    def test_apply_compare_and_swap_and_pointer_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, _, registry = write_fixture(root)
            path = root / ".alk/project-profile.json"
            old = path.read_bytes()
            proposal = setup_proposal({"projectProfile": profile, "registry": registry})
            with self.assertRaises(LifecycleError):
                apply_setup(root, path, proposal, "0" * 64)
            self.assertEqual(path.read_bytes(), old)
            expected = hashlib.sha256(old).hexdigest()
            with (
                patch("agent_lifecycle.cli.model_setup.replace_authority_bytes", side_effect=OSError("commit failed")),
                self.assertRaises(OSError),
            ):
                apply_setup(root, path, proposal, expected)
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(len(list((root / ".alk/host-launch").glob("stage-bindings-*.json"))), 1)
            applied = apply_setup(root, path, proposal, expected)
            self.assertTrue(applied["applied"])
            current = json.loads(path.read_text())
            self.assertTrue((root / current["policies"]["executionBindings"]).is_file())

    def test_apply_first_creation_and_symlink_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, _, registry = write_fixture(root)
            path = root / ".alk/project-profile.json"
            path.unlink()
            proposal = setup_proposal({"projectProfile": profile, "registry": registry})
            apply_setup(root, path, proposal, "ABSENT")
            path.unlink()
            target = root / "outside.json"
            target.write_text("{}")
            path.symlink_to(target)
            with self.assertRaises(LifecycleError):
                apply_setup(root, path, proposal, "ABSENT")
            self.assertEqual(target.read_text(), "{}")

    def test_default_availability_is_zero_process_and_local_view_is_explicit(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("agent_lifecycle.cli.model_setup.launch_from_local_profile") as launch,
        ):
            root = Path(tmp)
            write_fixture(root)
            argv = ["model", "availability", "--binding", "primary", "--project-profile", ".alk/project-profile.json"]
            code, local = run_cli(root, argv)
            self.assertEqual(code, 0)
            self.assertEqual(local["visibility"], "LOCAL_ONLY")
            self.assertEqual(local["model"], "private-model")
            self.assertEqual(local["status"], "UNAVAILABLE")
            code, portable = run_cli(root, [*argv, "--portable"])
            self.assertEqual(code, 0)
            self.assertNotIn("private-model", json.dumps(portable))
            launch.assert_not_called()

    def test_probe_missing_authority_never_launches(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("agent_lifecycle.cli.model_setup.launch_from_local_profile") as launch,
        ):
            root = Path(tmp)
            write_fixture(root)
            code, result = run_cli(
                root,
                [
                    "model",
                    "availability",
                    "--binding",
                    "primary",
                    "--project-profile",
                    ".alk/project-profile.json",
                    "--probe",
                ],
            )
            self.assertNotEqual(code, 0)
            self.assertEqual(result["code"], "model-probe-missing-input")
            launch.assert_not_called()

    def test_discovery_only_known_version_help_with_bounded_capture(self) -> None:
        runner = Mock(return_value={"status": "PASS", "stdoutTail": "codex 0.167.0"})
        with (
            patch("agent_lifecycle.cli.model_setup.shutil.which", side_effect=lambda name: "/known/" + name),
            patch("agent_lifecycle.cli.model_setup.run_process", runner),
        ):
            result = discover_local_tools()
        self.assertEqual(result["processCalls"], 6)
        self.assertFalse(result["modelCallsStarted"])
        for call in runner.call_args_list:
            self.assertIn(call.args[0][1:], (["--help"], ["--version"]))
            self.assertLessEqual(call.kwargs["timeout_seconds"], 5)
            self.assertEqual(call.kwargs["max_output_bytes"], 65536)

    def test_setup_rejects_stage_shapes_before_traversal_and_preserves_intermediate_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile, _, registry = write_fixture(root)
            invalid_stages: tuple[Any, ...] = (None, [], "invalid", {"implementation": None}, {"implementation": []})
            for stages in invalid_stages:
                with self.subTest(stages=stages):
                    payload = {"projectProfile": {**profile, "stages": stages}, "registry": registry}
                    with self.assertRaises(LifecycleError) as invalid:
                        setup_proposal(payload)
                    self.assertEqual(invalid.exception.code, "model-setup-profile-invalid")
                    before = (root / ".alk/project-profile.json").read_bytes()
                    (root / "bad-setup.json").write_text(json.dumps(payload))
                    code, result = run_cli(root, ["model", "setup", "--manual", "--input", "bad-setup.json"])
                    self.assertNotEqual(code, 0)
                    self.assertEqual(result["code"], "model-setup-profile-invalid")
                    self.assertEqual((root / ".alk/project-profile.json").read_bytes(), before)
            proposal = setup_proposal({"projectProfile": {"stages": {}}, "registry": registry})
            self.assertEqual(proposal["status"], "READY")
            # Full final project validation still runs at the public CLI boundary.
            (root / "intermediate.json").write_text(
                json.dumps({"projectProfile": {"stages": {}}, "registry": registry})
            )
            code, _ = run_cli(root, ["model", "setup", "--manual", "--input", "intermediate.json"])
            self.assertNotEqual(code, 0)

    def test_probe_cwd_options_reject_attached_foreign_and_keep_same_root(self) -> None:
        from agent_lifecycle.cli.model_setup import _require_probe_containment

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prefix = ["codex", "exec", "--sandbox", "read-only"]
            for values in (
                ["--cd", str(root)],
                ["-C", str(root)],
                ["--cd=" + str(root)],
                ["-C" + str(root)],
                ["--cd=."],
            ):
                _require_probe_containment(prefix + values, root)
            for values in (
                ["--cd=/outside"],
                ["-C/outside"],
                ["--cd", "/outside"],
                ["-C"],
                ["--cd="],
                ["--cd=../outside"],
            ):
                with self.subTest(values=values), self.assertRaises(LifecycleError) as refused:
                    _require_probe_containment(prefix + values, root)
                self.assertEqual(refused.exception.code, "model-probe-containment-required")

    def test_portable_probe_omits_local_launch_fields_but_keeps_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, entry, _ = write_fixture(root)
            inspected = stage_launch.inspect_binding(root, entry)
            selection = {
                "stage": "implementation",
                "modelClass": "strong-reasoning",
                "selectedBindingDigest": inspected["bindingDigest"],
                "localProcessResult": {
                    "status": "PASS",
                    "processStarted": True,
                    "exitCode": 0,
                    "stdout": "Usage: codex exec --help",
                },
            }
            args = SimpleNamespace(
                operation_id="UNIT_ONLY",
                task="QPROBE",
                manifest="unused-unit.json",
                lock="unused-unit-lock.json",
                source_revision="UNIT_ONLY",
                expected_revision=1,
                portable=True,
            )
            marker = root / ".alk/host-launch/probe-UNIT_ONLY-private.json"
            marker.write_text('{"status":"DISPATCH_PENDING","test":"UNIT_ONLY"}')
            launch = {
                "status": "PASS",
                "hostLaunchStarted": True,
                "receiptDigest": "f" * 64,
                "cwd": str(root),
                "argv": [str(root / "private.py")],
                "sessionPath": str(root / "session"),
            }
            with patch("agent_lifecycle.cli.model_setup.launch_from_local_profile", return_value=launch):
                view = _run_probe(args, root, inspected, selection, root / "state.json", {"attempt": 1}, {}, marker)
            self.assertNotIn(str(root), json.dumps(view))
            self.assertEqual(set(view["launch"]), {"status", "hostLaunchStarted", "receiptDigest"})
            local = json.loads(marker.with_name(marker.stem + "-result.json").read_text())
            self.assertEqual(local["launch"], launch)
