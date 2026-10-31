"""Bounded public-CLI consumer; fixture bootstrap is explicitly UNIT_ONLY.

ALK_EXTERNAL_CONSUMER_EXECUTABLE selects a source/editable or wheel-installed
console script. Consumer subprocesses use a disposable cwd and no PYTHONPATH.
ALK_EXTERNAL_CONSUMER_RECEIPTS optionally retains exact subprocess observations.
No fixture attestation represents a live host, reviewer or qualification.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((Path(__file__).parent / "fixtures/external-consumer-cases.json").read_text(encoding="utf-8"))
MAX_OUTPUT_BYTES = 1024 * 1024


class ConsumerRefusal(ValueError):
    """The external client's contract mapping forbids a mutation."""


class PublicCliConsumer:
    """Generic caller: only stdlib, public argv and public JSON artifacts."""

    def __init__(self, executable: str, cwd: Path) -> None:
        self.executable = str(Path(executable).absolute())
        self.cwd = cwd
        self.calls: list[dict] = []
        self.qualified = False

    def call(self, args: list[str]) -> tuple[int, dict]:
        if len(args) > 96 or sum(map(len, args)) > 16384:
            raise ConsumerRefusal("argv exceeds consumer limit")
        env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
            if key in os.environ
        }
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
        command = [self.executable, *args]
        started = datetime.now(UTC).isoformat()
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(
                command,
                cwd=self.cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=20,
                shell=False,
                check=False,
            )
            stdout.seek(0)
            stderr.seek(0)
            out = stdout.read(MAX_OUTPUT_BYTES + 1)
            err = stderr.read(MAX_OUTPUT_BYTES + 1)
        record = {
            "commandId": str(uuid.uuid4()),
            "argv": command,
            "cwd": str(self.cwd),
            "env": env,
            "executableSha256": hashlib.sha256(Path(self.executable).read_bytes()).hexdigest(),
            "startedAt": started,
            "finishedAt": datetime.now(UTC).isoformat(),
            "exitCode": result.returncode,
            "stdout": out.decode("utf-8"),
            "stderr": err.decode("utf-8"),
            "stdoutSha256": hashlib.sha256(out).hexdigest(),
            "stderrSha256": hashlib.sha256(err).hexdigest(),
            "evidenceBoundary": "UNIT_ONLY",
            "providerTokens": None,
            "providerUSD": None,
        }
        self.calls.append(record)
        if receipt_path := os.environ.get("ALK_EXTERNAL_CONSUMER_RECEIPTS"):
            with Path(receipt_path).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        if len(out) > MAX_OUTPUT_BYTES or len(err) > MAX_OUTPUT_BYTES:
            raise ConsumerRefusal("result is unknown: output exceeds consumer limit")
        payload = json.loads(out)
        if not isinstance(payload, dict):
            raise ConsumerRefusal("result is unknown: expected a JSON object")
        return result.returncode, payload

    def negotiate(self, *, versions: tuple[str, ...], schema: str) -> dict:
        self.qualified = False
        code, receipt = self.call(["version"])
        if code != 0 or receipt.get("schemaVersion") != schema or receipt.get("version") not in versions:
            raise ConsumerRefusal("unsupported version/schema; mutation refused")
        self.qualified = True
        return receipt

    def continue_args(self, operation: str, *, revision: int = 1) -> list[str]:
        return [
            "workflow",
            "continue",
            "--state",
            "run.state.json",
            "--manifest",
            "plans/package/plan.manifest.json",
            "--lock",
            "plans/package/plan.lock.json",
            "--operation-id",
            operation,
            "--expected-revision",
            str(revision),
            "--source-revision",
            "source",
            "--reason",
            "UNIT_ONLY external consumer conformance",
        ]

    def apply(self, args: list[str], projection: dict) -> tuple[int, dict]:
        if not self.qualified:
            raise ConsumerRefusal("negotiate before mutation")
        if projection.get("schemaVersion") != CASES["continuationSchema"]:
            raise ConsumerRefusal("unsupported receipt schema")
        action = projection.get("action", {})
        if action.get("schemaVersion") != CASES["actionSchema"] or action.get("route") != "run-start":
            raise ConsumerRefusal("unsupported action")
        return self.call(
            [
                *args,
                "--apply",
                "--projected-state-revision",
                str(action["stateRevision"]),
                "--projected-action-digest",
                action["actionDigest"],
            ]
        )

    def reconcile_run_start(self, operation: str, projection: dict) -> dict:
        """Read native authority after a lost reply; never dispatch a second mutation."""
        state = json.loads((self.cwd / "run.state.json").read_text(encoding="utf-8"))
        events = [json.loads(line) for line in (self.cwd / state["eventLog"]).read_text(encoding="utf-8").splitlines()]
        matches = [event for event in events if event.get("operationId") == operation]
        if len(matches) != 1:
            raise ConsumerRefusal("UNKNOWN: operation has no unique committed event")
        event = matches[0]
        expected = projection["action"]["stateRevision"] + 1
        if (
            event.get("schemaVersion") != "agent-workflow-event.v1"
            or event.get("runId") != state["runId"]
            or event.get("packageId") != state["packageId"]
            or event.get("stateRevision") != expected
            or state["stateRevision"] != expected
            or event.get("eventType") != "execution-started"
            or state["phase"] != "RUNNING"
            or state["planDigest"] != projection["action"]["planDigest"]
            or state["sourceRevision"] != projection["action"]["sourceRevision"]
        ):
            raise ConsumerRefusal("UNKNOWN: state/event/request bindings disagree")
        return event


def _inventory(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


class ConsumerEnvironmentTests(unittest.TestCase):
    def test_safe_ambient_windows_home_is_preserved_without_source_or_secret_environment(self) -> None:
        home_names = ("USERPROFILE", "HOMEDRIVE", "HOMEPATH")
        forbidden = ("PYTHONPATH", "PYTHONHOME", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "unit-only-cli"
            executable.write_bytes(b"unit-only controlled executable fingerprint")
            for homes in (
                {"USERPROFILE": r"C:\Users\unit-only", "HOMEDRIVE": "C:", "HOMEPATH": r"\Users\unit-only"},
                {},
            ):
                captured = {}

                def controlled_run(command, **kwargs):
                    captured.update(kwargs["env"])
                    kwargs["stdout"].write(b'{"schemaVersion":"agent-lifecycle-version.v1","version":"2.35.0"}')
                    return subprocess.CompletedProcess(command, 0)

                ambient = {"PATH": os.defpath, "SYSTEMROOT": r"C:\Windows", "TEMP": directory, "TMP": directory,
                           **homes, **dict.fromkeys(forbidden, "unit-only-placeholder")}
                with self.subTest(homePresent=bool(homes)), patch.dict(os.environ, ambient, clear=True), patch(
                    "tests.cli.test_external_consumer_contract.subprocess.run", side_effect=controlled_run
                ) as run:
                    code, payload = PublicCliConsumer(str(executable), root).call(["version"])
                self.assertEqual(code, 0)
                self.assertEqual(payload["version"], "2.35.0")
                run.assert_called_once()
                self.assertEqual({name: captured[name] for name in home_names if name in captured}, homes)
                self.assertTrue(set(forbidden).isdisjoint(captured))
                self.assertEqual(captured["PYTHONDONTWRITEBYTECODE"], "1")
                self.assertEqual(captured["PYTHONNOUSERSITE"], "1")


class ExternalConsumerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.executable = os.environ.get("ALK_EXTERNAL_CONSUMER_EXECUTABLE") or shutil.which("agent-lifecycle")
        if not cls.executable:
            raise RuntimeError("install the source package or set ALK_EXTERNAL_CONSUMER_EXECUTABLE")

    def setUp(self) -> None:
        # The private helper belongs solely to disposable test setup. It is
        # never imported by PublicCliConsumer or a consumer subprocess.
        from tests.workflow.test_workflow_run import _write_bundle

        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name).resolve()
        _write_bundle(self.root, phase="READY", task_status="READY")
        self.consumer = PublicCliConsumer(self.executable, self.root)
        self.consumer.negotiate(versions=tuple(CASES["testedVersions"]), schema=CASES["versionSchema"])

    def project(self, operation: str) -> tuple[list[str], dict]:
        args = self.consumer.continue_args(operation)
        code, receipt = self.consumer.call(args)
        self.assertEqual(code, 0)
        self.assertEqual(receipt["schemaVersion"], CASES["continuationSchema"])
        self.assertEqual(receipt["status"], "READY")
        self.assertEqual(receipt["mode"], "PROJECT")
        self.assertFalse(receipt["stateWritten"])
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertEqual(receipt["action"]["schemaVersion"], CASES["actionSchema"])
        state = json.loads((self.root / "run.state.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["action"]["planDigest"], state["planDigest"])
        self.assertEqual(receipt["action"]["sourceRevision"], state["sourceRevision"])
        self.assertEqual(receipt["action"]["operationId"], operation)
        self.assertEqual(receipt["action"]["stateRevision"], state["stateRevision"])
        return args, receipt

    def test_readonly_projection(self) -> None:
        before = _inventory(self.root)
        self.project("readonly-projection")
        self.assertEqual(_inventory(self.root), before)

    def test_guarded_action(self) -> None:
        args, projection = self.project("guarded-action")
        code, applied = self.consumer.apply(args, projection)
        self.assertEqual(code, 0)
        self.assertEqual(applied["status"], "APPLIED")
        self.assertEqual(applied["mode"], "APPLY")
        self.assertTrue(applied["stateWritten"])
        self.assertFalse(applied["modelCallsStarted"])
        self.assertFalse(applied["hostLaunchStarted"])
        event = self.consumer.reconcile_run_start("guarded-action", projection)
        for key, value in applied["appliedEvent"].items():
            self.assertEqual(event[key], value)

    def test_stale_guards(self) -> None:
        args, projection = self.project("stale-guards")
        before = _inventory(self.root)
        for revision, digest, expected in (
            (0, projection["action"]["actionDigest"], CASES["cases"][2]["codes"][0]),
            (1, "f" * 64, CASES["cases"][2]["codes"][1]),
        ):
            with self.subTest(expected=expected):
                code, receipt = self.consumer.call(
                    [
                        *args,
                        "--apply",
                        "--projected-state-revision",
                        str(revision),
                        "--projected-action-digest",
                        digest,
                    ]
                )
                self.assertEqual(code, 0)
                self.assertEqual(receipt["status"], "BLOCKED")
                self.assertEqual(receipt["blockers"][0]["code"], expected)
                self.assertFalse(receipt["stateWritten"])
                self.assertEqual(_inventory(self.root), before)

    def test_missing_required_input(self) -> None:
        args, _ = self.project("missing-input")
        before = _inventory(self.root)
        code, receipt = self.consumer.call([*args, "--apply"])
        self.assertEqual(code, 0)  # Exit zero alone is explicitly insufficient.
        self.assertEqual(receipt["status"], "INPUT_REQUIRED")
        self.assertTrue(receipt["requiredInputs"])
        self.assertFalse(receipt["stateWritten"])
        self.assertEqual(_inventory(self.root), before)

    def test_unattested_usage(self) -> None:
        decision = {
            "schemaVersion": "agent-lifecycle-model-route-decision.v1",
            "operationId": "route-op",
            "phase": "task-implementation",
            "sddTier": "S1",
            "routingPolicy": "balanced",
            "modelClass": "standard-code",
            "allowedFallbackModelClasses": ["strong-reasoning"],
            "targetContextWindow": "8k",
            "requiresUsageReceipt": True,
            "maxBillableTokens": 120000,
            "reasonCodes": ["tier-s1"],
            "profileDigest": "a" * 64,
            "decisionDigest": "b" * 64,
        }
        usage = {
            "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
            "operationId": "route-op",
            "host": "codex",
            "modelClass": "standard-code",
            "providerModelHash": "redacted",
            "routeDecisionDigest": "b" * 64,
            "usage": {
                "inputTokens": 1,
                "outputTokens": 1,
                "billableTokens": 2,
                "cumulativeContextBytes": 10,
                "toolCalls": 0,
                "wallSeconds": 1,
            },
            "attestation": {"source": "host", "status": "MISSING"},
        }
        self.write_json("decision.json", decision)
        self.write_json("usage.json", usage)
        self.refused(
            ["model", "usage-check", "--receipt", "usage.json", "--route-decision", "decision.json"],
            "model-usage-validation-failed",
        )

    def test_critical_model_route(self) -> None:
        self.write_json("routing.json", json.loads((ROOT / "profiles/model-routing-profile.v1.json").read_bytes()))
        self.write_json(
            "host.json",
            {
                "schemaVersion": "agent-lifecycle-host-model-profile.v1",
                "host": "unit-only",
                "profileId": "unqualified-compact",
                "bindings": {
                    "local-compact": {
                        "providerModel": "fixture-compact",
                        "contextWindow": "8k",
                        "capabilities": ["text", "json"],
                        "jsonReliability": "best-effort",
                        "toolUse": "unsupported",
                        "allowedForTiers": ["S0"],
                        "allowedForPhases": ["triage"],
                        "usageAccounting": "host-attested",
                        "dataPolicy": "local-only",
                        "calibrationStatus": "PASSED",
                    }
                },
            },
        )
        self.write_json(
            "request.json",
            {
                "schemaVersion": "agent-lifecycle-model-route-request.v1",
                "operationId": "critical-route",
                "phase": "final-audit",
                "sddTier": "S2",
                "riskFlags": {},
                "capabilityRequirements": ["text", "json", "tool-use", "deep-review"],
                "targetContextWindow": "8k",
                "routingPolicy": "local-only",
                "budgetClass": "normal",
                "userPolicy": {"localModelsAllowed": True, "cloudModelsAllowed": False},
            },
        )
        self.refused(
            ["model", "route", "--profile", "routing.json", "--host-profile", "host.json", "--request", "request.json"],
            "model-route-unsupported",
        )

    def test_lost_reply_reconciles_without_second_mutation(self) -> None:
        args, projection = self.project("lost-reply")
        self.consumer.apply(args, projection)  # Deliberately discard the reply.
        before = _inventory(self.root)
        self.consumer.reconcile_run_start("lost-reply", projection)
        self.consumer.reconcile_run_start("lost-reply", projection)  # Repeated delivery.
        code, receipt = self.consumer.call(self.consumer.continue_args("observe-after-lost-reply", revision=2))
        self.assertEqual(code, 0)
        self.assertFalse(receipt["stateWritten"])
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertEqual(_inventory(self.root), before)
        self.assertEqual(sum("--apply" in call["argv"] for call in self.consumer.calls), 1)
        self.assertEqual(len((self.root / "events.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_incompatible_version_or_schema_refuses_before_mutation(self) -> None:
        args, projection = self.project("incompatible-contract")
        before = _inventory(self.root)
        for versions, schema in (
            (("0.0.0",), CASES["versionSchema"]),
            (tuple(CASES["testedVersions"]), "unknown-version-schema.v99"),
        ):
            with self.subTest(versions=versions, schema=schema):
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.negotiate(versions=versions, schema=schema)
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.apply(args, projection)
        self.assertFalse(any("--apply" in call["argv"] for call in self.consumer.calls))
        self.assertEqual(_inventory(self.root), before)

    def write_json(self, name: str, payload: dict) -> None:
        (self.root / name).write_text(json.dumps(payload), encoding="utf-8")

    def refused(self, args: list[str], expected: str) -> None:
        before = _inventory(self.root)
        code, receipt = self.consumer.call(args)
        self.assertEqual(code, 2)
        self.assertEqual(receipt["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(receipt["code"], expected)
        self.assertEqual(_inventory(self.root), before)


if __name__ == "__main__":
    unittest.main()
