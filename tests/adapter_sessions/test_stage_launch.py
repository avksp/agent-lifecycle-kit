from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from agent_lifecycle.adapter_sessions import stage_launch
from agent_lifecycle.adapter_sessions.local_launch_profile import build_executable_identity
from agent_lifecycle.adapter_sessions.managed_process import _finish_managed_process, _LaunchContext
from agent_lifecycle.adapter_sessions.qualification import build_qualification_receipt
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.model_routing.availability import build_probe_observation
from agent_lifecycle.resources import builtin_profile_path


def write_fixture(root: Path) -> tuple[dict, dict, dict]:
    local = root / ".alk/host-launch"
    local.mkdir(parents=True)

    def write(name: str, payload: dict) -> dict:
        data = (json.dumps(payload) + "\n").encode()
        (local / name).write_bytes(data)
        return {"path": ".alk/host-launch/" + name, "sha256": hashlib.sha256(data).hexdigest()}

    host = {
        "schemaVersion": "agent-lifecycle-host-model-profile.v1",
        "profileId": "local-host",
        "host": "codex",
        "bindings": {
            "strong-reasoning": {
                "providerModel": "private-model",
                "contextWindow": "64k",
                "capabilities": ["text", "json", "tool-use", "code-edit", "deep-review"],
                "allowedForTiers": ["S0", "S1", "S2"],
                "allowedForPhases": ["task-implementation", "independent-review", "final-audit"],
                "jsonReliability": "strict",
                "toolUse": "supported",
                "usageAccounting": "host-attested",
                "dataPolicy": "cloud-allowed",
                "calibrationStatus": "PASSED",
            }
        },
    }
    launch = {
        "schemaVersion": "agent-local-host-launch-profile.v1",
        "status": "LOCAL_OPT_IN",
        "adapterId": "codex",
        "executable": sys.executable,
        "argvTemplate": ["exec", "--sandbox", "read-only", "return a bounded result"],
        "versionProbeArgs": ["--version"],
        "env": {"allow": ["PATH"], "allowPatterns": [], "projectPolicyAllowed": False},
        "timeoutSeconds": 30,
        "shell": False,
        "writesNativeConfig": False,
        "promptInjectionDefault": False,
        "publicSupportClaimed": False,
        "productionPromotionClaimed": False,
        "qualification": {
            "schemaVersion": "agent-host-launch-qualification-policy.v1",
            "expectedVersion": "0.167.0",
            "receiptFile": "qualified.json",
            "requiredForManagedTask": True,
            "maxPreflightProcesses": 1,
            "modelCallsForPreflight": 0,
        },
    }
    auth_home = root / ".codex"
    auth_home.mkdir(exist_ok=True)
    (auth_home / "auth.json").write_text('{"UNIT_ONLY":true}\n')
    identity = build_executable_identity(launch, profile_digest=canonical_digest(launch))
    receipt = build_qualification_receipt(
        profile=launch,
        profile_digest=canonical_digest(launch),
        probe_receipt={"status": "PASS", "stdout": {"tail": "codex 0.167.0"}},
        executable_identity=identity,
    )
    entry = {
        "adapterId": "codex",
        "hostModelProfile": {**write("host.json", host), "modelClass": "strong-reasoning"},
        "launchProfile": write("launch.json", launch),
        "hostParameters": {"reasoningEffort": "high"},
        "parameterSupport": {
            "allowedEfforts": ["none", "high"],
            "evidence": write("parameters.json", {"source": "https://developers.openai.com/codex/config-reference/"}),
        },
        "qualificationEvidence": write("qualified.json", receipt),
    }
    registry = {"schemaVersion": "agent-local-stage-bindings.v1", "bindings": {"primary": entry}}
    write("registry.json", registry)
    profile = {
        "schemaVersion": "agent-project-workflow-profile.v1",
        "profileId": "test",
        "defaultAdapter": "codex",
        "defaultMode": "implement",
        "defaultRisk": "auto",
        "policies": {"executionBindings": ".alk/host-launch/registry.json"},
        "stages": {"implementation": {"executionBindingRefs": ["primary"]}},
        "productionPromotionClaimed": False,
    }
    (root / ".alk/project-profile.json").write_text(json.dumps(profile))
    return profile, entry, registry


def select(root: Path, profile: dict, **kwargs: Any) -> dict:
    routing = json.loads(Path(builtin_profile_path("model-routing-profile.v1.json")).read_text())
    request = {
        "schemaVersion": "agent-lifecycle-model-route-request.v1",
        "operationId": "op",
        "phase": "task-implementation",
        "sddTier": "S2",
    }
    return stage_launch.select_stage_binding(
        root=root,
        profile=profile,
        profile_path=root / ".alk/project-profile.json",
        mode="implement",
        request=request,
        routing_profile=routing,
        **kwargs,
    )


class StageLaunchTests(unittest.TestCase):
    def test_official_document_redirect_host_is_supported_but_lookalikes_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, entry, _ = write_fixture(root)
            reference = entry["parameterSupport"]["evidence"]
            for source in (
                "https://learn.chatgpt.com/docs/config-file/config-reference",
                "https://learn.chatgpt.com.attacker.example/docs/config-file/config-reference",
            ):
                data = canonical_bytes({"source": source}) + b"\n"
                (root / reference["path"]).write_bytes(data)
                reference["sha256"] = hashlib.sha256(data).hexdigest()
                if "attacker.example" in source:
                    with self.assertRaises(LifecycleError) as caught:
                        stage_launch.inspect_binding(root, entry)
                    self.assertEqual(caught.exception.code, "stage-binding-parameter-evidence")
                else:
                    self.assertEqual(stage_launch.inspect_binding(root, entry)["entry"], entry)

    def test_first_explicit_probe_can_lack_availability_but_ordinary_cannot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, entry, _ = write_fixture(root)
            self.assertEqual(select(root, profile)["status"], "BLOCKED")
            selection = select(root, profile, explicit_probe=True)
            self.assertEqual(selection["status"], "READY")
            inspected = stage_launch.inspect_binding(root, entry)
            observation = build_probe_observation(
                availability=inspected["availability"],
                auth_revision_digest=inspected["authRevisionDigest"],
                launch={"status": "PASS", "hostLaunchStarted": True, "receiptDigest": "f" * 64},
                model_response={
                    "status": "PASS",
                    "responseDigest": "d" * 64,
                    "terminalDigest": "e" * 64,
                    "backendIdentityAttested": False,
                },
                now=int(stage_launch.time.time()),
                lineage={},
            )
            (root / ".alk/host-launch" / ("availability-" + selection["selectedBindingDigest"] + ".json")).write_text(
                json.dumps(observation)
            )
            self.assertEqual(select(root, profile)["status"], "READY")

    def test_canonical_qualification_path_digest_profile_version_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, entry, _ = write_fixture(root)
            inspected = stage_launch.inspect_binding(root, entry)
            self.assertEqual(stage_launch.require_binding_qualification(root, inspected)["status"], "PASS")
            for field, value in (
                ("profileDigest", "0" * 64),
                ("actualHostVersion", "0.166.0"),
                ("executableIdentity", {}),
                ("receiptDigest", "0" * 64),
            ):
                path = root / ".alk/host-launch/qualified.json"
                original = path.read_bytes()
                receipt = json.loads(original)
                receipt[field] = value
                if field != "receiptDigest":
                    receipt["receiptDigest"] = canonical_digest(
                        {key: item for key, item in receipt.items() if key != "receiptDigest"}
                    )
                raw = json.dumps(receipt).encode()
                path.write_bytes(raw)
                changed = copy.deepcopy(inspected)
                changed["entry"]["qualificationEvidence"]["sha256"] = hashlib.sha256(raw).hexdigest()
                with self.subTest(field=field), self.assertRaises(LifecycleError):
                    stage_launch.require_binding_qualification(root, changed)
                path.write_bytes(original)
            changed = copy.deepcopy(inspected)
            changed["entry"]["qualificationEvidence"]["path"] = ".alk/host-launch/other.json"
            with self.assertRaises(LifecycleError):
                stage_launch.require_binding_qualification(root, changed)
            (root / entry["qualificationEvidence"]["path"]).unlink()
            with self.assertRaises((LifecycleError, FileNotFoundError)):
                stage_launch.require_binding_qualification(root, inspected)

    def test_symlink_and_raw_digest_drift_refuse_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, entry, _ = write_fixture(root)
            path = root / entry["hostModelProfile"]["path"]
            path.write_text("{}")
            with self.assertRaises(LifecycleError):
                stage_launch.inspect_binding(root, entry)
            path.unlink()
            path.symlink_to(root / ".alk/host-launch/launch.json")
            with self.assertRaises(LifecycleError):
                stage_launch.inspect_binding(root, entry)

    def test_argv_reuses_canonical_pairs_and_treats_model_names_as_data(self) -> None:
        argv = ["codex", "exec", "--model", "$(private)", "--config", 'model_reasoning_effort="none"', "task"]
        self.assertEqual(stage_launch.compose_codex_argv(argv, model="$(private)", effort="none"), argv)
        for extra in (
            ["--model", "other"],
            ["--model", "$(private)"],
            ["-m", "$(private)"],
            ["--config", "model_provider=x"],
            ["--config", 'model_providers={custom={base_url="https://example.invalid"}}'],
            ["--config", 'model_providers.custom.base_url="https://example.invalid"'],
            ["--config", "model_reasoning_effort=low"],
            ["--profile", "another"],
            ["-mOTHER"],
            ["-cprofile=OTHER"],
            ["-cmodel_reasoning_effort=low"],
            ["-pOTHER"],
        ):
            with self.subTest(extra=extra), self.assertRaises(LifecycleError):
                stage_launch.compose_codex_argv(argv + extra, model="$(private)", effort="none")

    def test_argv_does_not_reinterpret_value_slots_or_delimited_prompt(self) -> None:
        argv = ["codex", "exec", "--output-last-message", "-mreport", "--", "-cprofile=literal prompt"]
        result = stage_launch.compose_codex_argv(argv, model="-model-data", effort="high")
        self.assertEqual(result[1:5], ["--model", "-model-data", "--config", 'model_reasoning_effort="high"'])
        self.assertEqual(result[5:], argv[1:])

    def test_probe_requires_complete_successful_model_response(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "UNIT_ONLY"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "UNIT_ONLY response"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        ]
        stdout = "\n".join(json.dumps(event) for event in events) + "\n"
        process = {"status": "PASS", "processStarted": True, "exitCode": 0, "stdout": stdout}
        witness = stage_launch.observe_codex_model_response(process)
        self.assertEqual(witness["status"], "PASS")
        self.assertFalse(witness["backendIdentityAttested"])
        invalid: list[dict[str, Any]] = [
            {"stdout": "Usage: codex exec --help"},
            {"stdout": "codex 0.167.0"},
            {"stdout": json.dumps(events[-1])},
            {"stdout": stdout + json.dumps({"type": "error", "message": "UNIT_ONLY"})},
            {"stdout": stdout + '{"type":'},
            {"stdout": stdout + json.dumps(events[-1])},
            {"stdout": "x" * 65537},
            {"stdoutRedacted": True},
            {"timedOut": True},
            {"cancelled": True},
            {"outputLimitExceeded": True},
            {"processStarted": False},
            {"exitCode": 1},
        ]
        for delta in invalid:
            with self.subTest(delta=list(delta)):
                self.assertEqual(
                    stage_launch.observe_codex_model_response({**process, **delta})["status"], "UNAVAILABLE"
                )

    def test_every_jsonl_event_requires_strict_bounded_json_before_observation(self) -> None:
        messages = ["private protocol first", '  private protocol final "quoted"  ']
        terminal = {"type": "turn.completed"}
        events = [
            {"type": "thread.started", "thread_id": "UNIT_ONLY"},
            {"type": "tool", "ratio": 0.25, "count": 3},
            *[{"type": "item.completed", "item": {"type": "agent_message", "text": text}} for text in messages],
            terminal,
        ]
        stdout = "\n" + "\n".join("  " + json.dumps(event) + "  " for event in events) + "\n\n"
        process: dict[str, Any] = {"status": "PASS", "processStarted": True, "exitCode": 0, "stdout": stdout}
        witness = stage_launch.observe_codex_model_response(process)
        self.assertEqual(witness["status"], "PASS")
        self.assertEqual(witness["responseDigest"], canonical_digest(messages))
        self.assertEqual(witness["lastResponseDigest"], canonical_digest(messages[-1].strip()))
        self.assertEqual(witness["responseCount"], 2)
        self.assertEqual(witness["terminalDigest"], canonical_digest(terminal))
        availability = {"bindingDigest": "a" * 64, "configurationDigest": "b" * 64, "executableDigest": "c" * 64}
        launch = {"status": "PASS", "hostLaunchStarted": True, "receiptDigest": "d" * 64}
        positive = build_probe_observation(
            availability=availability,
            auth_revision_digest="e" * 64,
            launch=launch,
            now=100,
            lineage={"scope": "UNIT_ONLY"},
            model_response=witness,
        )
        self.assertEqual(positive["status"], "PASS")
        bad_lines = {
            "duplicate-text": (
                '{"type":"item.completed","item":{"type":"agent_message","text":"first","text":"second"}}'
            ),
            "duplicate-item-type": (
                '{"type":"item.completed","item":{"type":"tool","type":"agent_message","text":"second"}}'
            ),
            "duplicate-event-type": (
                '{"type":"tool","type":"item.completed","item":{"type":"agent_message","text":"second"}}'
            ),
            "duplicate-tool-member": '{"type":"tool","result":{"value":1,"value":2}}',
            "nonfinite-nan": '{"type":"tool","value":NaN}',
            "nonfinite-infinity": '{"type":"tool","value":Infinity}',
            "nonfinite-negative-infinity": (
                '{"type":"item.completed","item":{"type":"agent_message","text":"second","value":-Infinity}}'
            ),
            "overflow-positive": '{"type":"tool","value":1e999}',
            "overflow-negative": '{"type":"tool","value":-1e999}',
            "depth-array": '{"type":"tool","value":' + "[" * 140 + "0" + "]" * 140 + "}",
            "depth-object": '{"type":"tool","value":' + '{"v":' * 140 + "0" + "}" * 140 + "}",
            "recursion-depth": '{"type":"tool","value":' + '{"v":' * 2000 + "0" + "}" * 2000 + "}",
            "escaped-surrogate": '{"type":"tool","value":"\\ud800"}',
            "raw-surrogate": '{"type":"tool","value":"' + chr(0xD800) + '"}',
            "non-object-event": "[]",
        }
        invalid: list[tuple[str, dict[str, Any]]] = [
            (name, {"stdout": line + "\n" + stdout}) for name, line in bad_lines.items()
        ]
        invalid += [
            ("help", {"stdout": "Usage: codex exec --help"}),
            ("version", {"stdout": "codex 0.167.0"}),
            ("no-message", {"stdout": json.dumps(terminal)}),
            ("terminal-not-last", {"stdout": stdout + json.dumps({"type": "tool"})}),
            ("truncated", {"stdout": stdout + '{"type":'}),
            ("duplicate-terminal", {"stdout": stdout + json.dumps(terminal)}),
            ("error", {"stdout": json.dumps({"type": "error"}) + "\n" + stdout}),
            ("oversized", {"stdout": "x" * 65537}),
            ("redacted", {"stdoutRedacted": True}),
            ("timeout", {"timedOut": True}),
            ("cancelled", {"cancelled": True}),
            ("output-limit", {"outputLimitExceeded": True}),
            ("not-started", {"processStarted": False}),
            ("nonzero-exit", {"exitCode": 1}),
        ]
        for name, delta in invalid:
            with self.subTest(case=name):
                current = {**process, **delta}
                response = stage_launch.observe_codex_model_response(current)
                self.assertEqual(response["status"], "UNAVAILABLE")
                self.assertNotIn("lastResponseDigest", response)
                self.assertFalse(response["backendIdentityAttested"])
                selection = {
                    "stage": "implementation",
                    "modelClass": "strong-reasoning",
                    "invocationDigest": "f" * 64,
                    "localProcessResult": current,
                }
                observed = stage_launch.stage_launch_receipt(
                    {**launch, "stdout": {"tail": current["stdout"]}}, selection
                )
                self.assertEqual(observed["modelResponse"]["status"], "UNAVAILABLE")
                self.assertEqual(observed["stdout"], {"tail": "", "redacted": True})
                self.assertNotIn("private protocol", json.dumps(observed))
                probe = build_probe_observation(
                    availability=availability,
                    auth_revision_digest="e" * 64,
                    launch=launch,
                    now=100,
                    lineage={"scope": "UNIT_ONLY"},
                    model_response=response,
                )
                self.assertEqual(probe["status"], "UNAVAILABLE")
                self.assertIsNone(probe["actualTokens"])
                self.assertIsNone(probe["actualUSD"])

    def test_unknown_primary_blocks_but_missing_executable_may_use_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, entry, registry = write_fixture(root)
            reserve = copy.deepcopy(entry)
            reserve["hostParameters"]["reasoningEffort"] = "none"
            registry["bindings"]["reserve"] = reserve
            profile["stages"]["implementation"]["executionBindingRefs"].append("reserve")
            (root / ".alk/host-launch/registry.json").write_text(json.dumps(registry))
            (root / ".alk/project-profile.json").write_text(json.dumps(profile))
            primary_view = stage_launch.inspect_binding(root, entry)
            reserve_view = stage_launch.inspect_binding(root, reserve)
            reserve_view["availability"]["status"] = "PASS"  # UNIT_ONLY cached observation fixture.
            with patch.object(stage_launch, "inspect_binding", side_effect=[primary_view, reserve_view]) as inspect:
                result = select(root, profile)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertIn("BINDING_AVAILABILITY_UNKNOWN", result["reasonCodes"])
                self.assertEqual(inspect.call_count, 1)
            primary_view["identity"]["status"] = "UNAVAILABLE"
            with patch.object(stage_launch, "inspect_binding", side_effect=[primary_view, reserve_view]):
                result = select(root, profile)
                self.assertEqual(result["status"], "READY")
                self.assertEqual(result["bindingId"], "reserve")

    def test_active_attempt_cannot_switch_even_before_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, _, _ = write_fixture(root)
            with self.assertRaises(LifecycleError) as caught:
                select(root, profile, state={"tasks": [{"status": "RUNNING"}]})
            self.assertEqual(caught.exception.code, "stage-binding-active-attempt")

    def test_portable_launch_receipt_cannot_leak_local_identity_or_stdout(self) -> None:
        messages = ["private initial response", "  private final response  "]
        terminal = {"type": "turn.completed"}
        stdout = "\n".join(
            json.dumps(event)
            for event in [
                *[{"type": "item.completed", "item": {"type": "agent_message", "text": text}} for text in messages],
                terminal,
            ]
        )
        process = {"status": "PASS", "processStarted": True, "exitCode": 0, "stdout": stdout}
        selection = {
            "stage": "implementation",
            "modelClass": "strong-reasoning",
            "bindingId": "private-binding",
            "invocationDigest": "a" * 64,
            "localProcessResult": process,
        }
        receipt = {
            "status": "PASS",
            "argv": ["private-model", "high"],
            "stdout": {"tail": stdout},
            "hostLaunchStarted": True,
        }
        result = stage_launch.stage_launch_receipt(receipt, selection)
        self.assertNotIn("private", json.dumps(result))
        self.assertTrue(result["modelCallsStarted"])
        witness = result["modelResponse"]
        self.assertEqual(witness["responseDigest"], canonical_digest(messages))
        self.assertEqual(witness["lastResponseDigest"], canonical_digest(messages[-1].strip()))
        self.assertEqual(witness["responseCount"], 2)
        self.assertEqual(witness["terminalDigest"], canonical_digest(terminal))
        self.assertFalse(witness["backendIdentityAttested"])
        portable = stage_launch.portable_stage_start(result, selection)
        self.assertEqual(portable["modelResponse"], witness)
        self.assertNotIn("private", json.dumps(portable))
        for delta in (
            {"stdout": None},
            {"stdout": stdout + '{"type":'},
            {"stdoutRedacted": True},
            {"timedOut": True},
            {"exitCode": 1},
            {"stdout": "x" * 65537},
        ):
            selection["localProcessResult"] = {**process, **delta}
            observed = stage_launch.stage_launch_receipt(receipt, selection)
            self.assertEqual(observed["modelResponse"]["status"], "UNAVAILABLE")
            self.assertNotIn("lastResponseDigest", observed["modelResponse"])
            self.assertNotIn("private", json.dumps(observed))

    def test_guard_refuses_missing_authority_and_input_drift_without_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, _, _ = write_fixture(root)
            selection = select(root, profile, explicit_probe=True)
            state_path = root / "state.json"
            state = {
                "sourceRevision": "a" * 40,
                "stateRevision": 5,
                "authorization": {"granted": False},
                "tasks": [
                    {"id": "WS-01", "status": "RUNNING", "attempt": 1, "attemptDeadlineAt": "2099-01-01T00:00:00Z"}
                ],
            }
            state_path.write_text(json.dumps(state))
            selection = stage_launch.seal_stage_launch(
                selection, state_path=state_path, task_id="WS-01", source_revision="a" * 40
            )
            runner = Mock()
            context = _LaunchContext(
                root=root,
                relative=selection["inspected"]["launchPath"],
                profile=selection["inspected"]["launch"],
                profile_digest=selection["launchProfileDigest"],
                profile_adapter="codex",
                env={},
                env_receipt={},
                timeout_seconds=30,
                shipped_digest=None,
                runner=runner,
            )
            guarded = stage_launch.guarded_stage_context(
                context, selection, operation="managedTask", route_id=None, requested_claim=None, input_request=None
            )
            result = guarded.runner([sys.executable, "exec"], env={}, timeout_seconds=30)
            self.assertFalse(result["processStarted"])
            self.assertEqual(result["blockers"][0]["code"], "authorization-required")
            (root / ".alk/host-launch/parameters.json").write_text("{}")
            result = guarded.runner([sys.executable, "exec"], env={}, timeout_seconds=30)
            self.assertEqual(result["blockers"][0]["code"], "stage-binding-input-drift")
            runner.assert_not_called()

    def test_unknown_effect_has_one_dispatch_and_no_second_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, _, _ = write_fixture(root)
            selection = select(root, profile, explicit_probe=True)
            state_path = root / "state.json"
            state = {
                "runDeadlineAt": "2099-01-01T00:00:00Z",
                "tasks": [{"id": "WS-01", "attemptDeadlineAt": "2099-01-01T00:00:00Z"}],
            }
            state_path.write_text(json.dumps(state))
            selection.update(statePath=str(state_path), taskId="WS-01")
            runner = Mock(return_value={"status": "FAIL"})
            inspected = selection["inspected"]
            context = _LaunchContext(
                root=root,
                relative=inspected["launchPath"],
                profile=inspected["launch"],
                profile_digest=selection["launchProfileDigest"],
                profile_adapter="codex",
                env={},
                env_receipt={},
                timeout_seconds=30,
                shipped_digest=None,
                runner=runner,
            )
            guarded = stage_launch.guarded_stage_context(
                context, selection, operation="managedTask", route_id=None, requested_claim=None, input_request=None
            )
            with patch.object(stage_launch, "verify_stage_sink"):
                for _ in range(2):
                    with self.assertRaises(LifecycleError) as error:
                        _finish_managed_process(
                            guarded,
                            argv=[sys.executable, "exec"],
                            session_id="probe",
                            risk_profile={"profileDigest": "r" * 64},
                            qualification_receipt=None,
                            host_identity={},
                        )
                    self.assertEqual(error.exception.code, "local-launch-start-uncertain")
            runner.assert_called_once()

    def test_special_exact_route_opt_in_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, _, _ = write_fixture(root)
            selection = select(root, profile, explicit_probe=True)
            with self.assertRaises(LifecycleError) as caught:
                stage_launch.guarded_stage_context(
                    None,
                    selection,
                    operation="managedTask",
                    route_id="codex-exact-prompt-v1",
                    requested_claim=None,
                    input_request=None,
                )
            self.assertEqual(caught.exception.code, "stage-binding-special-route-refused")

    def test_auth_link_target_metadata_invalidates_cache_without_credential_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile, entry, _ = write_fixture(root)
            auth = root / ".codex/auth.json"
            target = root / "UNIT_ONLY-credential-target"
            target.write_text("UNIT_ONLY original")
            auth.unlink()
            auth.symlink_to(target)
            with patch.object(Path, "open", side_effect=AssertionError("credential contents must not be read")):
                initial = stage_launch.auth_revision_digest({}, root)
            selected = select(root, profile, explicit_probe=True)
            inspected = stage_launch.inspect_binding(root, entry)
            self.assertEqual(inspected["authRevisionStatus"], "PASS")
            observation = build_probe_observation(
                availability=inspected["availability"],
                auth_revision_digest=inspected["authRevisionDigest"],
                launch={"status": "PASS", "hostLaunchStarted": True, "receiptDigest": "f" * 64},
                model_response={
                    "status": "PASS",
                    "responseDigest": "d" * 64,
                    "terminalDigest": "e" * 64,
                    "backendIdentityAttested": False,
                },
                now=int(stage_launch.time.time()),
                lineage={},
            )
            path = root / ".alk/host-launch" / ("availability-" + selected["selectedBindingDigest"] + ".json")
            path.write_text(json.dumps(observation))
            self.assertEqual(select(root, profile)["status"], "READY")
            link_before = auth.lstat()
            target.write_text("UNIT_ONLY changed target with different metadata")
            self.assertEqual(auth.lstat(), link_before)
            self.assertNotEqual(initial, stage_launch.auth_revision_digest({}, root))
            self.assertEqual(select(root, profile)["status"], "BLOCKED")
            target.unlink()
            unavailable = stage_launch.inspect_binding(root, entry)
            self.assertEqual(unavailable["authRevisionStatus"], "UNAVAILABLE")
            self.assertEqual(unavailable["availability"]["status"], "UNAVAILABLE")

    def test_selection_uses_one_current_profile_snapshot_and_refuses_stale_object(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile, _, _ = write_fixture(root)
            path = root / ".alk/project-profile.json"
            path.write_text(json.dumps(profile, indent=4) + "\n")
            raw = path.read_bytes()
            selected = select(root, profile, explicit_probe=True)
            self.assertEqual(selected["pins"][".alk/project-profile.json"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(selected["projectProfileDigest"], canonical_digest(profile))
            replacement = {**profile, "profileId": "UNIT_ONLY replacement"}
            path.write_text(json.dumps(replacement))
            with self.assertRaises(LifecycleError) as stale:
                select(root, profile, explicit_probe=True)
            self.assertEqual(stale.exception.code, "stage-binding-project-profile-drift")
            path.write_bytes(raw)
            original_reader = stage_launch.read_authority_bytes
            profile_reads = []

            def read_once(value: Path, **kwargs: Any) -> bytes:
                data = original_reader(value, **kwargs)
                if value == path:
                    profile_reads.append(data)
                    path.write_text(json.dumps(replacement))
                return data

            with patch.object(stage_launch, "read_authority_bytes", side_effect=read_once):
                selected = select(root, profile, explicit_probe=True)
            self.assertEqual(profile_reads, [raw])
            self.assertEqual(selected["projectProfileDigest"], canonical_digest(profile))
            self.assertEqual(selected["pins"][".alk/project-profile.json"], hashlib.sha256(raw).hexdigest())
            with self.assertRaises(LifecycleError) as changed:
                stage_launch.verify_stage_sink(SimpleNamespace(root=root), selected)
            self.assertEqual(changed.exception.code, "stage-binding-input-drift")
