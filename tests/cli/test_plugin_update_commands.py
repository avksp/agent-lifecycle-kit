from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_bytes
from agent_lifecycle.diagnostics.plugin_updates import check_plugin_updates
from tests.contracts.test_plugin_update_schemas import make_descriptor, make_request
from tests.diagnostics.test_plugin_update_network import fixture_client, publication_metadata
from tests.planning.test_update_impact import write_plan

SOURCE = Path(__file__).resolve().parents[2] / "src"


class PluginUpdateCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = make_request(host={"adapterId": "codex", "version": "0.167.1"})
        self.write("request.json", self.request)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_bytes(value) + b"\n")

    def run_cli(self, *argv, success=True):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "agent_lifecycle", *argv],
            cwd=self.root,
            env=dict(os.environ, PYTHONPATH=str(SOURCE), PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0 if success else 2, (argv, result.stdout, result.stderr))
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def action(self, name, *argv, success=True):
        return self.run_cli("plugin-update", name, "--request", "request.json", *argv, success=success)

    def assess(self):
        _, inventory = write_plan(self.root)
        self.write("inventory.json", inventory)
        self.write("release.json", make_descriptor())
        return self.action(
            "assess", "--release", "release.json", "--inventory", "inventory.json", "--out", "assessment.json"
        )

    def test_all_five_actions_dispatch_and_install_is_an_actual_refusal(self):
        assessment = self.assess()
        self.assertEqual(assessment["status"], "ASSESSED")
        offer = self.action("offer", "--assessment", "assessment.json", "--out", "offer.json")
        self.assertEqual(offer["status"], "OFFERED")
        self.assertEqual(offer["details"]["commandStatus"], "INERT_OPERATOR_RECIPE_NOT_QUALIFIED_EXECUTION")
        install = self.action("install", "--offer", "offer.json")
        self.assertEqual(install["status"], "UNSUPPORTED")
        self.assertEqual(install["details"]["reason"], "NATIVE_INSTALL_UNQUALIFIED")
        reconcile = self.action("reconcile")
        self.assertEqual(reconcile["status"], "UNKNOWN")
        self.write("request.json", make_request(mode="off"))
        check = self.action("check")
        self.assertEqual(check["status"], "OFF")
        for report in (assessment, offer, install, reconcile, check):
            self.assertFalse(report["authorityClaimed"])
            self.assertEqual(report["modelCallsStarted"], 0)
            self.assertEqual(report["nativeProcessesStarted"], 0)

    def test_schema_registry_exports_five_closed_public_definitions(self):
        for name in ("request", "report", "cache"):
            schema = self.run_cli("schema", "show", f"agent-plugin-update-{name}.v1")
            self.assertFalse(schema["additionalProperties"])
        for name in ("release-impact", "plan-inventory"):
            schema = self.run_cli("schema", "show", f"agent-plugin-{name}.v1")
            self.assertFalse(schema["additionalProperties"])

    def test_cached_discovery_is_a_fixture_only_and_uses_real_cli_without_http(self):
        client, _ = fixture_client(publication_metadata())
        cache = check_plugin_updates(self.request, client=client, now=int(time.time()))["details"]["cache"]
        self.write("updates.cache.json", cache)
        before = (self.root / "updates.cache.json").read_bytes()
        report = self.action("check", "--cache", "updates.cache.json")
        self.assertEqual(report["details"]["provenance"], "CACHED_LOCAL_RECORD")
        self.assertEqual((self.root / "updates.cache.json").read_bytes(), before)
        self.assertFalse(report["authorityClaimed"])

    def test_output_is_create_only_and_cannot_alias_request_or_plan(self):
        self.assess()
        for name in ("request.json", "assessment.json", "plan/plan.manifest.json"):
            before = (self.root / name).read_bytes()
            self.action("offer", "--assessment", "assessment.json", "--out", name, success=False)
            self.assertEqual((self.root / name).read_bytes(), before)

    def test_output_and_cache_reject_unsafe_scope_before_network(self):
        for path in (
            "../escape.json",
            ".git/new.json",
            ".codex/new.json",
            ".alk/new.json",
            "tasks/new.json",
            "run.state.json",
            ".ALK/new.json",
            ".aLk/new.json",
            ".GIT/new.json",
            ".CoDeX/new.json",
            ".ClAuDe/new.json",
            "TaSkS/new.json",
            "run.STATE.JSON",
            "nested/PLAN.LOCK.JSON",
            "nested/PLAN.MANIFEST.JSON",
        ):
            with self.subTest(path=path):
                self.action("check", "--out", path, success=False)
                self.action("check", "--cache", path, success=False)
        self.action("check", "--cache", "request.json", success=False)
        self.assertEqual(set(self.root.iterdir()), {self.root / "request.json"})

    def test_incomplete_assessment_cannot_create_missing_plan_input_or_any_output(self):
        manifest, inventory = write_plan(self.root)
        missing = "plan/not-created.md"
        manifest["planFiles"] = [missing]
        self.write("plan/plan.manifest.json", manifest)
        self.write("inventory.json", inventory)
        self.write("release.json", make_descriptor())
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for output in (missing, "incomplete-report.json"):
            with self.subTest(output=output):
                report = self.action(
                    "assess",
                    "--release",
                    "release.json",
                    "--inventory",
                    "inventory.json",
                    "--out",
                    output,
                    success=False,
                )
                self.assertEqual(report["code"], "plugin-update-incomplete-assessment-output")
                self.assertFalse((self.root / output).exists())
        report = self.action("assess", "--release", "release.json", "--inventory", "inventory.json")
        self.assertEqual(report["status"], "UNKNOWN")
        self.assertFalse(report["details"]["assessmentComplete"])
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    @unittest.skipIf(os.name == "nt", "symlink creation needs optional Windows privilege")
    def test_symlink_input_and_output_parent_refuse(self):
        (self.root / "linked.json").symlink_to("request.json")
        self.run_cli("plugin-update", "reconcile", "--request", "linked.json", success=False)
        (self.root / "linked").symlink_to(self.root, target_is_directory=True)
        self.action("check", "--out", "linked/result.json", success=False)
        self.assertFalse((self.root / "result.json").exists())

    def test_stale_assessed_plan_refuses_without_writing_or_changing_plan(self):
        self.assess()
        path = self.root / "plan/acceptance-criteria.md"
        path.write_text("changed after assessment\n")
        before = path.read_bytes()
        self.action("offer", "--assessment", "assessment.json", "--out", "offer.json", success=False)
        self.assertFalse((self.root / "offer.json").exists())
        self.assertEqual(path.read_bytes(), before)

    def test_unsupported_auto_and_notify_do_not_create_cache_or_dispatch(self):
        for mode in ("safe-auto", "notify"):
            self.write("request.json", make_request(mode=mode, triggerQualified=True))
            report = self.action("check", "--cache", "updates.cache.json")
            self.assertEqual(report["status"], "UNSUPPORTED")
            self.assertEqual(report["nativeProcessesStarted"], 0)
            self.assertFalse((self.root / "updates.cache.json").exists())

    def test_off_and_unsupported_checks_do_not_read_an_existing_malformed_cache(self):
        cache = self.root / "updates.cache.json"
        cache.write_bytes(b"not JSON; cache must not be read for this mode")
        before = cache.read_bytes()
        for mode in ("off", "safe-auto", "notify"):
            self.write("request.json", make_request(mode=mode))
            report = self.action("check", "--cache", "updates.cache.json")
            self.assertEqual(report["status"], "OFF" if mode == "off" else "UNSUPPORTED")
            self.assertEqual(cache.read_bytes(), before)

    def test_invalid_json_duplicate_key_and_malformed_inventory_are_bounded_errors(self):
        for raw in (b'{"schemaVersion":"bad","schemaVersion":"bad"}', b'{"x":NaN}', b"{"):
            (self.root / "request.json").write_bytes(raw)
            self.action("reconcile", success=False)
        self.write("request.json", self.request)
        self.write("release.json", make_descriptor())
        self.write("inventory.json", {"schemaVersion": "agent-plugin-plan-inventory.v1", "plans": None})
        self.action("assess", "--release", "release.json", "--inventory", "inventory.json", success=False)

    def test_changed_assessment_request_binding_refuses_before_output(self):
        report = self.assess()
        report = copy.deepcopy(report)
        report["requestDigest"] = "f" * 64
        self.write("changed.json", report)
        self.action("offer", "--assessment", "changed.json", "--out", "offer.json", success=False)
        self.assertFalse((self.root / "offer.json").exists())

    def test_unknown_host_is_unsupported_not_an_automatic_fallback(self):
        self.assess()
        self.write("request.json", make_request(host={"adapterId": "unknown", "version": "1.0"}))
        report = self.action("offer", "--assessment", "assessment.json")
        self.assertEqual(report["status"], "UNSUPPORTED")
        self.assertNotIn("commands", report["details"])
