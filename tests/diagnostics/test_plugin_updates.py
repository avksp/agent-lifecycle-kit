from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import agent_lifecycle
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.diagnostics.plugin_updates import (
    check_plugin_updates,
    observe_update_identities,
    store_update_cache,
)
from tests.contracts.test_plugin_update_schemas import make_request
from tests.diagnostics.test_plugin_update_network import fixture_client, publication_metadata


class PluginUpdatesTests(unittest.TestCase):
    def test_retained_target_channel_and_descriptor_mismatches_refuse_before_network(self):
        cases = ("pin", "explicit", "prerelease", "descriptor-version", "descriptor-commit", "publication")
        for case in cases:
            request = make_request(pin="v2.48.0") if case == "pin" else make_request()
            if case == "explicit":
                request["targetVersion"] = "2.48.0"
            client, _ = fixture_client(publication_metadata())
            cache = check_plugin_updates(request, client=client, now=10000)["details"]["cache"]
            self.assertEqual(cache["policyDigest"], canonical_digest(request))
            candidate = cache["candidate"]
            if case in ("pin", "explicit"):
                candidate.update(version="2.49.0", tag="v2.49.0")
            elif case == "prerelease":
                candidate.update(version="2.48.0-alpha", tag="v2.48.0-alpha")
            elif case == "descriptor-version":
                candidate["releaseImpact"]["version"] = "2.49.0"
            elif case == "descriptor-commit":
                candidate["releaseImpact"]["sourceCommit"] = "c" * 40
            else:
                candidate["publication"]["plugin"]["url"] = "https://untrusted.example/plugin.zip"
            unused, calls = fixture_client({})
            with self.subTest(case=case), self.assertRaises(LifecycleError):
                check_plugin_updates(request, cache=cache, client=unused, now=10001)
            self.assertEqual(calls, [])

    def test_installed_label_does_not_fill_missing_loaded_identity(self):
        request = make_request(observations={"installedPlugin": {"version": agent_lifecycle.__version__}})
        identities = observe_update_identities(request)
        self.assertIsNone(identities["loadedInstructions"]["version"])
        self.assertEqual(identities["loadedInstructions"]["provenance"], "UNAVAILABLE")
        self.assertEqual(identities["activeCompatibility"], "UNKNOWN")

    def test_matching_labels_are_declared_not_attested(self):
        request = make_request(
            observations={
                key: {"version": agent_lifecycle.__version__} for key in ("installedPlugin", "loadedInstructions")
            }
        )
        identities = observe_update_identities(request)
        self.assertEqual(identities["labelComparison"], "DECLARED_MATCH")
        self.assertEqual(identities["installedPlugin"]["provenance"], "DECLARED")
        self.assertEqual(identities["activeCompatibility"], "UNKNOWN")

    def test_supplied_runtime_cannot_override_running_package(self):
        request = make_request(
            observations={"runtime": {"version": "0.0.1"}, "loadedInstructions": {"version": "0.0.1"}}
        )
        identities = observe_update_identities(request)
        self.assertEqual(identities["runtime"]["version"], agent_lifecycle.__version__)
        self.assertEqual(identities["runtime"]["provenance"], "OBSERVED_RUNNING_PACKAGE")
        self.assertEqual(identities["labelComparison"], "DRIFT")

    def test_cache_cadence_reuses_observation_without_network_or_new_authority(self):
        client, _ = fixture_client(publication_metadata())
        report = check_plugin_updates(make_request(), client=client, now=10000)
        cache = report["details"]["cache"]
        unused, calls = fixture_client({})
        replay = check_plugin_updates(make_request(), cache=cache, client=unused, now=10001)
        self.assertEqual(calls, [])
        self.assertEqual(replay["details"]["provenance"], "CACHED_LOCAL_RECORD")
        self.assertIs(replay["authorityClaimed"], False)

    def test_offline_expired_cache_keeps_last_success_and_staleness(self):
        client, _ = fixture_client(publication_metadata())
        cache = check_plugin_updates(make_request(), client=client, now=10000)["details"]["cache"]
        offline, _ = fixture_client({next(iter(publication_metadata())): URLError("offline")})
        report = check_plugin_updates(make_request(), cache=cache, client=offline, now=100000)
        self.assertEqual(report["status"], "STALE")
        self.assertEqual(report["details"]["lastSuccess"]["sourceCommit"], "a" * 40)
        self.assertIs(report["details"]["cacheUpdated"], True)
        retained = report["details"]["cache"]
        self.assertEqual(retained["observedAt"], 10000)
        self.assertEqual(retained["lastAttemptAt"], 100000)
        self.assertEqual(retained["candidate"], cache["candidate"])
        unused, calls = fixture_client({})
        replay = check_plugin_updates(make_request(), cache=retained, client=unused, now=100001)
        self.assertEqual(replay["status"], "STALE")
        self.assertEqual(calls, [])
        self.assertEqual(replay["details"]["cache"], retained)

    def test_changed_policy_future_cache_and_changed_tag_refuse(self):
        client, _ = fixture_client(publication_metadata())
        cache = check_plugin_updates(make_request(), client=client, now=10000)["details"]["cache"]
        for request, now in ((make_request(pin="v2.48.0"), 10001), (make_request(), 9999)):
            with self.subTest(request=request, now=now), self.assertRaises(LifecycleError):
                check_plugin_updates(request, cache=cache, now=now)
        rows = publication_metadata()
        ref = next(key for key in rows if "/git/ref/" in key)
        rows[ref]["object"]["sha"] = "c" * 40
        changed, _ = fixture_client(rows)
        report = check_plugin_updates(make_request(), cache=cache, client=changed, now=15000)
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertIs(report["details"]["cacheUpdated"], True)

    def test_cache_cannot_overwrite_input_or_non_cache_authority(self):
        client, _ = fixture_client(publication_metadata())
        cache = check_plugin_updates(make_request(), client=client, now=10000)["details"]["cache"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protected = root / "run.state.json"
            protected.write_bytes(b'{"phase":"RUNNING"}')
            before = protected.read_bytes()
            with self.assertRaises(LifecycleError):
                store_update_cache(root, "run.state.json", cache)
            self.assertEqual(protected.read_bytes(), before)
            with self.assertRaises(LifecycleError):
                store_update_cache(root, "request.json", cache, inputs=("request.json",))
            self.assertFalse((root / "request.json").exists())

    def test_cache_create_and_replace_use_existing_safe_writers(self):
        client, _ = fixture_client(publication_metadata())
        cache = check_plugin_updates(make_request(), client=client, now=10000)["details"]["cache"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_update_cache(root, "updates.cache.json", cache)
            updated = copy.deepcopy(cache)
            updated["observedAt"] = 20000
            updated["lastAttemptAt"] = 20000
            store_update_cache(root, "updates.cache.json", updated)
            self.assertEqual((root / "updates.cache.json").read_bytes(), canonical_bytes(updated) + b"\n")

    def test_first_failure_retained_record_suppresses_network_until_hour_and_recovers(self):
        request = make_request()
        offline, calls = fixture_client({next(iter(publication_metadata())): URLError("private exception text")})
        failed = check_plugin_updates(request, client=offline, now=10000)
        cache = failed["details"]["cache"]
        self.assertEqual(len(calls), 1)
        self.assertIsNone(cache["observedAt"])
        self.assertIsNone(cache["candidate"])
        self.assertEqual(cache["lastAttemptAt"], 10000)
        self.assertNotIn(b"private exception text", canonical_bytes(failed))
        for timestamp in (10000, 10001, 13599):
            unused, calls = fixture_client({})
            replay = check_plugin_updates(request, cache=cache, client=unused, now=timestamp)
            self.assertEqual(replay["status"], "UNAVAILABLE")
            self.assertEqual(replay["details"]["networkRequests"], 0)
            self.assertEqual(calls, [])
        client, calls = fixture_client(publication_metadata())
        success = check_plugin_updates(request, cache=cache, client=client, now=13600)["details"]["cache"]
        self.assertTrue(calls)
        self.assertEqual(success["observedAt"], 13600)
        self.assertEqual(success["lastAttemptAt"], 13600)
        self.assertNotIn("lastFailureReason", success)

    def test_recent_success_failure_keeps_original_success_and_negative_cache_cadence(self):
        request = make_request()
        client, _ = fixture_client(publication_metadata())
        original = check_plugin_updates(request, client=client, now=10000)["details"]["cache"]
        before = copy.deepcopy(original)
        offline, _ = fixture_client({next(iter(publication_metadata())): URLError("offline")})
        failed = check_plugin_updates(request, cache=original, client=offline, now=14000)
        retained = failed["details"]["cache"]
        self.assertEqual(failed["status"], "UNAVAILABLE")
        self.assertEqual(retained["observedAt"], 10000)
        self.assertEqual(retained["candidate"], original["candidate"])
        self.assertEqual(original, before)
        unused, calls = fixture_client({})
        replay = check_plugin_updates(request, cache=retained, client=unused, now=17599)
        self.assertEqual(replay["status"], "UNAVAILABLE")
        self.assertEqual(calls, [])

    def test_negative_cache_future_policy_and_off_modes_are_checked_before_network(self):
        request = make_request()
        offline, _ = fixture_client({next(iter(publication_metadata())): URLError("offline")})
        cache = check_plugin_updates(request, client=offline, now=10000)["details"]["cache"]
        for policy, timestamp in ((request, 9999), (make_request(pin="v2.48.0"), 10001)):
            unused, calls = fixture_client({})
            with self.subTest(policy=policy, timestamp=timestamp), self.assertRaises(LifecycleError):
                check_plugin_updates(policy, cache=cache, client=unused, now=timestamp)
            self.assertEqual(calls, [])
        for mode in ("off", "notify", "safe-auto"):
            with patch("agent_lifecycle.diagnostics.plugin_updates._cache_candidate") as read:
                check_plugin_updates(make_request(mode=mode), cache={"malformed": True}, now=10001)
                read.assert_not_called()

    def test_legacy_positive_cache_defaults_last_attempt_to_observation(self):
        client, _ = fixture_client(publication_metadata())
        cache = check_plugin_updates(make_request(), client=client, now=10000)["details"]["cache"]
        del cache["lastAttemptAt"]
        unused, calls = fixture_client({})
        report = check_plugin_updates(make_request(), cache=cache, client=unused, now=10001)
        self.assertIn(report["status"], ("AVAILABLE", "CURRENT"))
        self.assertEqual(calls, [])

    def test_library_cache_refuses_alk_root_before_creation(self):
        client, _ = fixture_client(publication_metadata())
        cache = check_plugin_updates(make_request(), client=client, now=10000)["details"]["cache"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(LifecycleError):
                store_update_cache(root, ".alk/updates.cache.json", cache)
            self.assertFalse((root / ".alk").exists())

    def test_library_cache_refuses_case_aliases_before_writer_or_parent_io(self):
        client, _ = fixture_client(publication_metadata())
        cache = check_plugin_updates(make_request(), client=client, now=10000)["details"]["cache"]
        names = [f"{directory}/updates.cache.json" for directory in (".ALK", ".aLk", ".GIT", ".Codex", "TaSkS")]
        names.extend(("nested/run.STATE.JSON", "nested/plan.LOCK.JSON", "nested/PLAN.MANIFEST.JSON"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in names:
                with (
                    self.subTest(name=name),
                    patch("agent_lifecycle.diagnostics.plugin_updates.create_authority_bytes") as create,
                    patch("agent_lifecycle.diagnostics.plugin_updates.replace_authority_bytes") as replace,
                    patch("agent_lifecycle.diagnostics.plugin_updates.read_update_json") as read,
                    patch.object(Path, "exists") as exists,
                    patch.object(Path, "is_symlink") as symlink,
                    self.assertRaises(LifecycleError),
                ):
                    store_update_cache(root, name, cache)
                create.assert_not_called()
                replace.assert_not_called()
                read.assert_not_called()
                exists.assert_not_called()
                symlink.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])
