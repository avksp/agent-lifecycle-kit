from __future__ import annotations

import copy
import importlib.resources
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_lifecycle
from agent_lifecycle.adapter_sessions.plugin_updates import (
    offer_plugin_update,
    reconcile_plugin_update,
    refuse_plugin_install,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.planning.update_impact import assess_plugin_update
from tests.contracts.test_plugin_update_schemas import make_descriptor, make_request
from tests.planning.test_update_impact import snapshot, write_plan


def offer_fixture(root, *, phase=None, frozen=False):
    _, inventory = write_plan(root, status="FROZEN" if phase or frozen else "DRAFT", phase=phase)
    request = make_request(
        mode="ask", pin="v2.48.0", host={"adapterId": "codex", "version": "0.167.1", "scope": "user"}
    )
    assessment = assess_plugin_update(request, make_descriptor(), inventory, repository_root=root)
    return request, assessment


class PluginUpdateHostAdviceTests(unittest.TestCase):
    def test_shipped_descriptor_null_commit_is_unknown_and_explicit_derived_copy_can_offer(self):
        source = importlib.resources.files("agent_lifecycle").joinpath("data/plugin-updates/release-impact.v1.json")
        shipped = source.read_bytes()
        descriptor = load_json_object(shipped)
        self.assertIsNone(descriptor["sourceCommit"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, inventory = write_plan(root)
            request = make_request(host={"adapterId": "codex", "version": "0.167.1"})
            assessment = assess_plugin_update(request, descriptor, inventory, repository_root=root)
            report = offer_plugin_update(request, assessment, repository_root=root)
            self.assertEqual(report["status"], "UNKNOWN")
            self.assertIn("TARGET_COMMIT_UNRESOLVED", report["details"]["reason"])
            self.assertNotIn("commands", report["details"])
            from agent_lifecycle.diagnostics.plugin_updates import check_plugin_updates
            from tests.diagnostics.test_plugin_update_network import fixture_client, publication_metadata

            rows = publication_metadata()
            key = next(key for key in rows if key.endswith("release-impact.v1.json"))
            rows[key] = descriptor
            client, _ = fixture_client(rows)
            discovery = check_plugin_updates(request, client=client, now=10000)
            candidate = discovery["details"]["candidate"]
            self.assertEqual(candidate["releaseImpact"], descriptor)
            derived = {**descriptor, "sourceCommit": candidate["sourceCommit"]}
            assessment = assess_plugin_update(request, derived, inventory, repository_root=root)
            report = offer_plugin_update(request, assessment, repository_root=root)
            self.assertEqual(report["status"], "OFFERED")
            self.assertEqual(report["details"]["assessmentTrust"], "DECLARED_LOCAL_REPORT_NOT_AUTHORITY")
            self.assertEqual(assessment["inputs"]["releaseDigest"], canonical_digest(derived))
            self.assertEqual(sha256_hex(source.read_bytes()), sha256_hex(shipped))
            self.assertIsNone(descriptor["sourceCommit"])

    def test_nonnull_malformed_target_commit_still_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request, assessment = offer_fixture(root)
            assessment["details"]["target"]["sourceCommit"] = "invalid"
            with self.assertRaises(LifecycleError):
                offer_plugin_update(request, assessment, repository_root=root)

    def test_manual_offer_is_inert_and_does_not_grant_global_or_native_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request, assessment = offer_fixture(root)
            before = snapshot(root)
            with patch("subprocess.run") as run, patch("subprocess.Popen") as popen:
                report = offer_plugin_update(request, assessment, repository_root=root)
            self.assertEqual(report["status"], "OFFERED")
            self.assertEqual(report["details"]["installationEligibility"], "UNQUALIFIED")
            self.assertEqual(report["details"]["target"]["sourceCommit"], "a" * 40)
            self.assertIn("UNKNOWN", report["details"]["globalEffectScope"])
            self.assertIs(report["authorityClaimed"], False)
            self.assertEqual(report["nativeProcessesStarted"], 0)
            run.assert_not_called()
            popen.assert_not_called()
            self.assertEqual(snapshot(root), before)

    def test_changed_plan_bytes_refuse_before_offer_and_do_not_overwrite_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request, assessment = offer_fixture(root)
            path = root / "plan/acceptance-criteria.md"
            path.write_bytes(path.read_bytes() + b"\nchanged\n")
            before = snapshot(root)
            with self.assertRaises(LifecycleError):
                offer_plugin_update(request, assessment, repository_root=root)
            self.assertEqual(snapshot(root), before)

    def test_foreign_path_and_per_plan_file_count_refuse_before_io(self):
        for kind in ("traversal", "too-many"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request, assessment = offer_fixture(root)
                hashes = (
                    {**assessment["details"]["plans"][0]["inputSHA256"], "../foreign/secret.json": "b" * 64}
                    if kind == "traversal"
                    else {f"plan/{i}.json": "b" * 64 for i in range(65)}
                )
                assessment["details"]["plans"][0]["inputSHA256"] = hashes
                with (
                    patch("agent_lifecycle.adapter_sessions.plugin_updates.read_stable_repository_file") as read,
                    self.assertRaises(LifecycleError),
                ):
                    offer_plugin_update(request, assessment, repository_root=root)
                read.assert_not_called()

    def test_changed_policy_target_and_commit_are_not_accepted_as_current_assessment(self):
        for field in ("policy", "target", "commit"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request, assessment = offer_fixture(root)
                if field == "policy":
                    request["mode"] = "manual"
                elif field == "target":
                    assessment["details"]["target"]["version"] = "2.49.0"
                else:
                    request["trustedTargetCommit"] = "c" * 40
                    assessment["requestDigest"] = canonical_digest(request)
                with self.assertRaises(LifecycleError):
                    offer_plugin_update(request, assessment, repository_root=root)

    def test_active_paused_unknown_and_frozen_without_run_state_defer(self):
        for phase in ("RUNNING", "PAUSED", "BLOCKED", "UNRECOGNIZED", None):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request, assessment = offer_fixture(root, phase=phase, frozen=True)
                report = offer_plugin_update(request, assessment, repository_root=root)
                self.assertEqual(report["status"], "UNKNOWN")
                self.assertNotIn("commands", report["details"])
                self.assertIn("DEFER_ACTIVATION", report["details"]["reason"])

    def test_completed_history_is_unchanged_and_never_qualifies_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request, assessment = offer_fixture(root, phase="COMPLETE")
            before = snapshot(root)
            report = offer_plugin_update(request, assessment, repository_root=root)
            self.assertEqual(report["status"], "OFFERED")
            self.assertEqual(snapshot(root), before)
            self.assertEqual(report["details"]["installationEligibility"], "UNQUALIFIED")

    def test_off_and_unqualified_automatic_modes_do_no_subject_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode, expected in (("off", "OFF"), ("safe-auto", "UNSUPPORTED"), ("notify", "UNSUPPORTED")):
                with (
                    self.subTest(mode=mode),
                    patch("agent_lifecycle.adapter_sessions.plugin_updates.read_stable_repository_file") as read,
                ):
                    result = offer_plugin_update(make_request(mode=mode), {}, repository_root=Path(tmp))
                    self.assertEqual(result["status"], expected)
                    self.assertEqual(result["nativeProcessesStarted"], 0)
                    read.assert_not_called()

    def test_other_or_missing_host_has_no_automatic_adapter_fallback(self):
        for host in (
            {},
            {"adapterId": "claude", "version": "1.0.0"},
            {"adapterId": "opencode", "version": "2.0.0"},
            {"adapterId": "grok", "version": "1.0.0"},
        ):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request, assessment = offer_fixture(root)
                request["host"] = host
                assessment["requestDigest"] = canonical_digest(request)
                report = offer_plugin_update(request, assessment, repository_root=root)
                self.assertEqual(report["status"], "UNSUPPORTED")
                self.assertNotIn("commands", report["details"])

    def test_install_refuses_every_nonoff_mode_without_dispatch_or_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request, assessment = offer_fixture(root)
            offer = offer_plugin_update(request, assessment, repository_root=root)
            for mode in ("manual", "ask", "safe-auto", "notify"):
                local = {**request, "mode": mode}
                view = copy.deepcopy(offer)
                view["requestDigest"] = canonical_digest(local)
                with self.subTest(mode=mode), patch("subprocess.run") as run:
                    result = refuse_plugin_install(local, view)
                    self.assertEqual(result["status"], "UNSUPPORTED")
                    self.assertEqual(result["details"]["reason"], "NATIVE_INSTALL_UNQUALIFIED")
                    self.assertEqual(result["nativeProcessesStarted"], 0)
                    run.assert_not_called()

    def test_caller_metadata_is_not_interpolated_into_native_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request, assessment = offer_fixture(root)
            malicious = "$(touch should-not-exist)"
            assessment["details"]["plans"][0]["gaps"].append(malicious)
            offer = offer_plugin_update(request, assessment, repository_root=root)
            self.assertNotIn(malicious, str(offer["details"]["commands"]))
            self.assertEqual(offer["details"]["commandStatus"], "INERT_OPERATOR_RECIPE_NOT_QUALIFIED_EXECUTION")
            self.assertFalse((root / "should-not-exist").exists())

    def test_reconcile_separates_running_runtime_from_unattested_loaded_labels(self):
        for version in (agent_lifecycle.__version__, "0.0.1"):
            request = make_request(
                observations={"installedPlugin": {"version": version}, "loadedInstructions": {"version": version}}
            )
            report = reconcile_plugin_update(request)
            expected = "UNKNOWN" if version == agent_lifecycle.__version__ else "DRIFT"
            self.assertEqual(report["status"], expected)
            self.assertEqual(report["details"]["identities"]["runtime"]["version"], agent_lifecycle.__version__)
            self.assertEqual(report["details"]["activation"], "NOT_ATTESTED_BY_CALLER_LABELS")
            self.assertIs(report["details"]["planMutation"], False)
