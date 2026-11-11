from __future__ import annotations

import copy
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.diagnostics.plugin_updates import (
    API_ROOT,
    PYPI_ROOT,
    RAW_ROOT,
    UpdateMetadataClient,
    _fetch_metadata,
    check_plugin_updates,
)
from tests.contracts.test_plugin_update_schemas import make_descriptor, make_request


def publication_metadata(version="2.48.0", annotated=False):
    tag = "v" + version
    digest = "b" * 64
    source = "https://github.com/avksp/agent-lifecycle-kit"
    plugin = "agent-lifecycle-kit-agent-plugin-" + tag + ".zip"
    rows = {
        API_ROOT + "releases/latest": {
            "tag_name": tag,
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": plugin,
                    "size": 100,
                    "digest": "sha256:" + digest,
                    "state": "uploaded",
                    "browser_download_url": source + "/releases/download/" + tag + "/" + plugin,
                }
            ],
        },
        API_ROOT + "git/ref/tags/" + tag: {"object": {"type": "tag" if annotated else "commit", "sha": "a" * 40}},
        PYPI_ROOT + version + "/json": {"info": {"name": "agent-lifecycle-kit", "version": version}, "urls": []},
        RAW_ROOT + "a" * 40 + "/.codex-plugin/plugin.json": {"name": "agent-lifecycle-kit", "version": version},
        RAW_ROOT + "a" * 40 + "/.agents/plugins/marketplace.json": {
            "plugins": [{"name": "agent-lifecycle-kit", "source": {"url": source + ".git", "ref": tag}}]
        },
    }
    for kind, suffix in (("bdist_wheel", "-py3-none-any.whl"), ("sdist", ".tar.gz")):
        name = "agent_lifecycle_kit-" + version + suffix
        rows[PYPI_ROOT + version + "/json"]["urls"].append(
            {
                "filename": name,
                "packagetype": kind,
                "yanked": False,
                "size": 200,
                "url": "https://files.pythonhosted.org/packages/example/" + name,
                "digests": {"sha256": digest},
            }
        )
    descriptor = make_descriptor()
    descriptor["version"] = version
    rows[RAW_ROOT + "a" * 40 + "/src/agent_lifecycle/data/plugin-updates/release-impact.v1.json"] = descriptor
    rows[API_ROOT + "git/tags/" + "a" * 40] = {"object": {"type": "commit", "sha": "a" * 40}}
    rows[API_ROOT + "releases/tags/" + tag] = copy.deepcopy(rows[API_ROOT + "releases/latest"])
    return rows


def fixture_client(rows):
    calls = []

    def fetch(url, timeout, maximum):
        calls.append((url, timeout, maximum))
        value = rows[url]
        if isinstance(value, Exception):
            raise value
        return canonical_bytes(value)

    return UpdateMetadataClient(fetch=fetch, clock=lambda: 0.0), calls


class PluginUpdateNetworkTests(unittest.TestCase):
    def setUp(self):
        # These are UNIT_ONLY metadata fixtures for a fixed predecessor/target pair.
        runtime = patch("agent_lifecycle.__version__", "2.47.0")
        runtime.start()
        self.addCleanup(runtime.stop)

    def test_split_official_channels_and_one_annotated_peel_share_caps(self):
        client, calls = fixture_client(publication_metadata(annotated=True))
        report = check_plugin_updates(make_request(), client=client, now=10000)
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(len(calls), 7)
        candidate = report["details"]["candidate"]
        self.assertEqual(set(candidate["publication"]), {"plugin", "sdist", "bdist_wheel"})
        self.assertEqual(candidate["publicationStatus"], "METADATA_COHERENT_CONTENT_UNVERIFIED")
        self.assertIs(candidate["installationReady"], False)

    def test_exact_pin_never_falls_back_to_latest(self):
        client, calls = fixture_client(publication_metadata())
        report = check_plugin_updates(make_request(pin="v2.48.0"), client=client, now=10000)
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(calls[0][0], API_ROOT + "releases/tags/v2.48.0")
        self.assertNotIn(API_ROOT + "releases/latest", [row[0] for row in calls])

    def test_yanked_duplicate_wrong_version_or_foreign_python_publication_refuse(self):
        for mutation in ("yanked", "duplicate", "version", "url", "name"):
            rows = publication_metadata()
            metadata = rows[PYPI_ROOT + "2.48.0/json"]
            if mutation == "yanked":
                metadata["urls"][0]["yanked"] = True
            elif mutation == "duplicate":
                metadata["urls"][1] = copy.deepcopy(metadata["urls"][0])
            elif mutation == "version":
                metadata["info"]["version"] = "2.47.0"
            elif mutation == "name":
                metadata["info"]["name"] = None
            else:
                metadata["urls"][0]["url"] = "https://untrusted.example/artifact.whl"
            with self.subTest(mutation=mutation):
                client, _ = fixture_client(rows)
                self.assertEqual(
                    check_plugin_updates(make_request(), client=client, now=10000)["status"], "UNAVAILABLE"
                )

    def test_missing_historical_descriptor_is_unknown_not_installation_success(self):
        rows = publication_metadata()
        url = RAW_ROOT + "a" * 40 + "/src/agent_lifecycle/data/plugin-updates/release-impact.v1.json"
        rows[url] = HTTPError(url, 404, "Not Found", {}, None)
        client, _ = fixture_client(rows)
        report = check_plugin_updates(make_request(), client=client, now=10000)
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertIsNone(report["details"]["candidate"]["releaseImpact"])
        self.assertIs(report["details"]["candidate"]["installationReady"], False)

    def test_marketplace_and_immutable_commit_mismatch_refuse(self):
        for field in ("marketplace", "commit"):
            rows = publication_metadata()
            request = make_request()
            if field == "marketplace":
                rows[RAW_ROOT + "a" * 40 + "/.agents/plugins/marketplace.json"]["plugins"][0]["source"]["ref"] = "main"
            else:
                request["trustedTargetCommit"] = "c" * 40
            client, _ = fixture_client(rows)
            with self.subTest(field=field):
                self.assertEqual(check_plugin_updates(request, client=client, now=10000)["status"], "UNAVAILABLE")

    def test_off_notify_safe_auto_and_unbounded_prerelease_start_no_request(self):
        for request in (
            make_request(mode="off"),
            make_request(mode="notify", triggerQualified=True),
            make_request(mode="safe-auto"),
            make_request(channel="prerelease"),
        ):
            client, calls = fixture_client({})
            with self.subTest(request=request):
                report = check_plugin_updates(request, client=client, now=10000)
                self.assertEqual(calls, [])
                self.assertEqual(report["nativeProcessesStarted"], 0)

    def test_network_request_and_total_time_caps_are_shared(self):
        client = UpdateMetadataClient(fetch=lambda *_: b"{}", clock=lambda: 0.0)
        for _ in range(8):
            client.get(API_ROOT + "releases/latest")
        with self.assertRaises(LifecycleError):
            client.get(API_ROOT + "releases/latest")
        client = UpdateMetadataClient(fetch=lambda *_: b"{}", clock=lambda: 0.0)
        client.clock = lambda: 11.0
        with self.assertRaises(LifecycleError):
            client.get(API_ROOT + "releases/latest")
        self.assertEqual(client.requests, 0)

    def test_oversized_response_and_aggregate_bytes_refuse(self):
        raw = canonical_bytes({str(i): "x" * 4000 for i in range(60)})
        client = UpdateMetadataClient(fetch=lambda *_: raw, clock=lambda: 0.0)
        for _ in range(4):
            client.get(API_ROOT + "releases/latest")
        with self.assertRaises(LifecycleError):
            client.get(API_ROOT + "releases/latest")
        self.assertLessEqual(client.bytes, 1048576)

    def test_foreign_or_redirect_shaped_endpoint_refuses_before_transport(self):
        client, calls = fixture_client({})
        for url in (
            "https://example.com",
            API_ROOT + "releases/latest?redirect=x",
            "https://api.github.com@untrusted.example/repos/avksp/agent-lifecycle-kit/releases/latest",
        ):
            with self.subTest(url=url), self.assertRaises(LifecycleError):
                client.get(url)
        self.assertEqual(calls, [])

    def test_unused_long_pypi_description_is_not_interpreted_or_returned(self):
        rows = publication_metadata()
        rows[PYPI_ROOT + "2.48.0/json"]["info"]["description"] = "UNTRUSTED NOTE " * 1500
        client, _ = fixture_client(rows)
        report = check_plugin_updates(make_request(), client=client, now=10000)
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertNotIn(b"UNTRUSTED NOTE", canonical_bytes(report))

    def test_parent_network_deadline_handles_a_blocked_reader_without_retry(self):
        with (
            patch(
                "agent_lifecycle.diagnostics.plugin_updates.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["reader"], 0.1),
            ) as run,
            self.assertRaises(LifecycleError) as caught,
        ):
            _fetch_metadata(API_ROOT + "releases/latest", 0.1, 100)
        self.assertEqual(caught.exception.code, "plugin-update-network-timeout")
        self.assertEqual(run.call_count, 1)
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertNotIn("HOME", run.call_args.kwargs["env"])
