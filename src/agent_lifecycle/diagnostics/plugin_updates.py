"""Bounded official metadata discovery and explicit version observations."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit

import agent_lifecycle
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.contracts.authority_io import create_authority_bytes, replace_authority_bytes
from agent_lifecycle.contracts.plugin_update_schemas import UPDATE_CACHE_SCHEMA, UPDATE_FAILURE_REASONS, UPDATE_SOURCE
from agent_lifecycle.contracts.plugin_update_validation import (
    MAX_UPDATE_BYTES,
    UPDATE_FORBIDDEN_ROOTS,
    read_update_json,
    require_update,
    update_bounds,
    update_digest,
    update_object,
    update_report,
    update_text,
    update_version,
    validate_release_impact,
    validate_update_cache,
    validate_update_request,
)

API_ROOT = "https://api.github.com/repos/avksp/agent-lifecycle-kit/"
RAW_ROOT = "https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/"
PYPI_ROOT = "https://pypi.org/pypi/agent-lifecycle-kit/"
CACHE_TTL_SECONDS = 86400
CACHE_CADENCE_SECONDS = 3600
MAX_METADATA_BYTES = 1048576
MAX_METADATA_REQUESTS = 8
MAX_ARTIFACT_BYTES = 67108864
FetchMetadata = Callable[[str, float, int], bytes]


_METADATA_READER = r"""
import base64, json, sys
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirect refused", headers, None)
try:
    request = Request(sys.argv[1], headers={"Accept":"application/json","User-Agent":"agent-lifecycle-kit-updates"})
    with build_opener(NoRedirect()).open(request, timeout=float(sys.argv[3])) as response:
        if response.url != sys.argv[1] or response.headers.get("Content-Encoding", "identity") != "identity":
            result = {"error":"origin-or-encoding"}
        else:
            result = {"body":base64.b64encode(response.read(int(sys.argv[2])+1)).decode("ascii")}
except HTTPError as exc:
    result = {"error":"HTTP","status":exc.code}
except (OSError, URLError, ValueError):
    result = {"error":"unavailable"}
print(json.dumps(result, separators=(",", ":")))
"""


def _fetch_metadata(url: str, timeout: float, maximum: int) -> bytes:
    # A socket timeout alone cannot bound slow-drip headers/body. This fixed,
    # isolated stdlib reader has a parent wall deadline and no host/model route.
    import os

    env = {key: os.environ[key] for key in ("SystemRoot",) if key in os.environ}
    try:
        process = subprocess.run(
            [sys.executable, "-I", "-B", "-S", "-c", _METADATA_READER, url, str(maximum), str(timeout)],
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise LifecycleError("plugin-update-network-timeout", "metadata total wall deadline") from None
    require_update(process.returncode == 0, "metadata reader unavailable")
    require_update(
        len(process.stdout) <= 4 * (maximum + 1) // 3 + 256 and len(process.stderr) <= 4096,
        "metadata reader output cap",
    )
    result = json.loads(process.stdout)
    if result.get("error") == "HTTP":
        raise HTTPError(url, result["status"], "metadata unavailable", Message(), None)
    require_update("body" in result and "error" not in result, "metadata origin/encoding unavailable")
    return base64.b64decode(result["body"], validate=True)


class UpdateMetadataClient:
    """One invocation's shared request, byte and wall caps; no retries."""

    def __init__(self, fetch: FetchMetadata | None = None, clock: Callable[[], float] | None = None) -> None:
        self.fetch = fetch or _fetch_metadata
        self.network_worker = fetch is None
        self.clock = clock or time.monotonic
        self.deadline = self.clock() + 10
        self.requests = 0
        self.bytes = 0
        self.sources: list[dict[str, Any]] = []

    def usage(self) -> dict[str, Any]:
        return {
            "networkRequests": self.requests,
            "networkBytes": self.bytes,
            "networkCountBasis": "CONSERVATIVE_ATTEMPTS_NOT_WIRE_ATTESTATION",
            "networkWorkerLaunchAttempts": self.requests if self.network_worker else 0,
            "networkElapsedSeconds": max(0.0, self.clock() - (self.deadline - 10)),
            "sources": self.sources,
        }

    def get(self, url: str) -> dict[str, Any]:
        require_update(_metadata_endpoint(url), "untrusted metadata endpoint")
        remaining = self.deadline - self.clock()
        require_update(remaining > 0 and self.requests < MAX_METADATA_REQUESTS, "metadata time/request cap")
        maximum = min(MAX_UPDATE_BYTES, MAX_METADATA_BYTES - self.bytes)
        require_update(maximum > 0, "metadata aggregate byte cap")
        self.requests += 1
        raw = self.fetch(url, remaining, maximum)
        require_update(isinstance(raw, bytes) and len(raw) <= maximum, "metadata response byte cap")
        self.bytes += len(raw)
        require_update(self.clock() <= self.deadline, "metadata total deadline")
        parsed = load_json_object(raw)
        canonical_bytes(parsed)  # Also rejects overflow-to-infinity or invalid Unicode in ignored fields.
        _metadata_depth(parsed)
        obj = _metadata_projection(url, parsed)
        update_bounds(obj)
        self.sources.append(
            {
                "url": url,
                "rawSHA256": sha256_hex(raw),
                "projectedSHA256": canonical_digest(obj),
                "bytes": len(raw),
                "projection": "IDENTITY_AND_PUBLICATION_FIELDS_ONLY",
            }
        )
        return obj


def _metadata_depth(value: Any, depth: int = 0) -> None:
    require_update(depth <= 16, "metadata JSON exceeds depth16")
    if isinstance(value, dict):
        for key, item in value.items():
            require_update(len(key) <= 4096, "metadata member name exceeds4096")
            _metadata_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _metadata_depth(item, depth + 1)


def _metadata_fields(value: Any, keys: tuple[str, ...]) -> Any:
    return {key: value[key] for key in keys if key in value} if isinstance(value, dict) else value


def _metadata_projection(url: str, value: dict[str, Any]) -> dict[str, Any]:
    # Descriptions/release notes are not update-wire fields. Keep their bounded
    # raw digest, never their text; a normal PyPI description can exceed4096.
    if url.startswith(PYPI_ROOT):
        urls = value.get("urls")
        if isinstance(urls, list):
            urls = [
                _metadata_fields(row, ("filename", "packagetype", "yanked", "size", "url", "digests")) for row in urls
            ]
        return {"info": _metadata_fields(value.get("info"), ("name", "version")), "urls": urls}
    if url.startswith(API_ROOT + "releases/") and "assets" in value:
        rows = value["assets"]
        assets = (
            [_metadata_fields(row, ("name", "size", "digest", "state", "browser_download_url")) for row in rows]
            if isinstance(rows, list)
            else rows
        )
        return {**_metadata_fields(value, ("tag_name", "draft", "prerelease")), "assets": assets}
    if "/git/ref/" in url or "/git/tags/" in url:
        return {"object": _metadata_fields(value.get("object"), ("type", "sha"))}
    if url.endswith("/.codex-plugin/plugin.json"):
        return _metadata_fields(value, ("name", "version"))
    if url.endswith("/.agents/plugins/marketplace.json"):
        rows = value.get("plugins")
        if isinstance(rows, list):
            rows = [
                {
                    **_metadata_fields(row, ("name",)),
                    "source": _metadata_fields(row.get("source"), ("url", "ref")),
                }
                if isinstance(row, dict)
                else row
                for row in rows
            ]
        return {"plugins": rows}
    return value


def _metadata_endpoint(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.fragment:
        return False
    return url.startswith((API_ROOT, RAW_ROOT, PYPI_ROOT)) and "?" not in url


def observe_update_identities(request: dict[str, Any]) -> dict[str, Any]:
    """Observe this Python runtime; caller-supplied host labels remain declared."""
    validate_update_request(request)
    observations = request.get("observations", {})
    result: dict[str, Any] = {
        "runtime": {"version": agent_lifecycle.__version__, "provenance": "OBSERVED_RUNNING_PACKAGE"}
    }
    for name in ("installedPlugin", "loadedInstructions"):
        supplied = observations.get(name, {})
        version = supplied.get("version")
        result[name] = {"version": version, "provenance": "DECLARED" if version else "UNAVAILABLE"}
    if "runtime" in observations:
        result["declaredRuntime"] = observations["runtime"]
    labels = [result[name]["version"] for name in ("runtime", "installedPlugin", "loadedInstructions")]
    known = [version for version in labels if version is not None]
    result["labelComparison"] = "UNKNOWN"
    if len(set(known)) > 1:
        result["labelComparison"] = "DRIFT"
    elif len(known) == 3:
        result["labelComparison"] = "DECLARED_MATCH"
    result["activeCompatibility"] = "UNKNOWN"
    result["reason"] = "File/runtime labels cannot attest loaded host instructions or all plan contracts"
    return result


def _release_tag(client: UpdateMetadataClient, tag: str) -> str:
    reference = client.get(API_ROOT + "git/ref/tags/" + tag)
    obj = reference.get("object", {})
    require_update(isinstance(obj, dict), "invalid tag reference")
    if obj.get("type") == "tag":
        annotated = client.get(API_ROOT + "git/tags/" + update_digest(obj.get("sha"), 40))
        obj = annotated.get("object", {})
    require_update(isinstance(obj, dict) and obj.get("type") == "commit", "tag must resolve once to a commit")
    return update_digest(obj.get("sha"), 40)


def _asset(row: dict[str, Any], filename: str, url: str, digest: Any) -> dict[str, Any]:
    size = row.get("size")
    require_update(type(size) is int and 0 < size <= MAX_ARTIFACT_BYTES, "invalid publication size")
    require_update(row.get("filename", row.get("name")) == filename, "publication filename mismatch")
    return {"filename": filename, "url": url, "sha256": update_digest(digest), "bytes": size}


def _plugin_asset(release: dict[str, Any], version: str) -> dict[str, Any]:
    filename = "agent-lifecycle-kit-agent-plugin-v" + version + ".zip"
    rows = release.get("assets")
    require_update(isinstance(rows, list), "missing release assets")
    rows = cast(list[Any], rows)
    matching = [row for row in rows if isinstance(row, dict) and row.get("name") == filename]
    require_update(len(matching) == 1, "missing/duplicate plugin asset")
    row = matching[0]
    url = UPDATE_SOURCE + "/releases/download/v" + version + "/" + filename
    require_update(
        row.get("browser_download_url") == url and row.get("state") == "uploaded", "untrusted/incomplete plugin asset"
    )
    digest = update_text(row.get("digest"))
    require_update(digest.startswith("sha256:"), "missing plugin digest")
    return _asset(row, filename, url, digest[7:])


def _python_assets(client: UpdateMetadataClient, version: str) -> dict[str, Any]:
    metadata = client.get(PYPI_ROOT + version + "/json")
    info = metadata.get("info", {})
    require_update(
        isinstance(info, dict)
        and info.get("version") == version
        and isinstance(info.get("name"), str)
        and info["name"].replace("_", "-").lower() == "agent-lifecycle-kit",
        "PyPI project/version mismatch",
    )
    urls = metadata.get("urls")
    require_update(isinstance(urls, list) and len(urls) == 2, "missing/duplicate Python publication")
    urls = cast(list[Any], urls)
    result = {}
    names = {
        "bdist_wheel": "agent_lifecycle_kit-" + version + "-py3-none-any.whl",
        "sdist": "agent_lifecycle_kit-" + version + ".tar.gz",
    }
    for row in urls:
        require_update(isinstance(row, dict), "invalid Python artifact metadata")
        kind = row.get("packagetype")
        require_update(
            kind in names and kind not in result and row.get("yanked") is False,
            "yanked, duplicate or unsupported Python artifact",
        )
        url = row.get("url")
        require_update(isinstance(url, str), "missing Python artifact locator")
        parsed = urlsplit(url)
        require_update(
            parsed.scheme == "https"
            and parsed.netloc == "files.pythonhosted.org"
            and parsed.path.endswith("/" + names[kind])
            and not parsed.query
            and not parsed.fragment,
            "untrusted Python artifact locator",
        )
        digests = row.get("digests", {})
        require_update(isinstance(digests, dict), "missing Python artifact digest")
        result[kind] = _asset(row, names[kind], url, digests.get("sha256"))
    return result


def _source_versions(client: UpdateMetadataClient, commit: str, version: str) -> None:
    plugin = client.get(RAW_ROOT + commit + "/.codex-plugin/plugin.json")
    require_update(
        plugin.get("name") == "agent-lifecycle-kit" and plugin.get("version") == version, "plugin version mismatch"
    )
    market = client.get(RAW_ROOT + commit + "/.agents/plugins/marketplace.json")
    plugins = market.get("plugins")
    require_update(isinstance(plugins, list), "missing marketplace entries")
    plugins = cast(list[Any], plugins)
    rows = [row for row in plugins if isinstance(row, dict) and row.get("name") == "agent-lifecycle-kit"]
    require_update(len(rows) == 1, "missing/duplicate marketplace plugin")
    source = rows[0].get("source", {})
    require_update(
        isinstance(source, dict) and source.get("url") == UPDATE_SOURCE + ".git" and source.get("ref") == "v" + version,
        "marketplace target/source mismatch",
    )


def _impact(client: UpdateMetadataClient, commit: str, version: str) -> tuple[dict[str, Any] | None, str]:
    url = RAW_ROOT + commit + "/src/agent_lifecycle/data/plugin-updates/release-impact.v1.json"
    try:
        descriptor = validate_release_impact(client.get(url))
    except HTTPError as exc:
        if exc.code == 404:
            return None, "UNAVAILABLE"
        raise
    require_update(
        descriptor["version"] == version and descriptor["sourceCommit"] in (None, commit),
        "descriptor source/version mismatch",
    )
    return descriptor, "DECLARED_MEANING_AT_OBSERVED_COMMIT"


def _discover(
    request: dict[str, Any], client: UpdateMetadataClient, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    target = request.get("targetVersion") or (request.get("pin") or "")[1:]
    url = API_ROOT + ("releases/tags/v" + target if target else "releases/latest")
    release = client.get(url)
    tag = update_text(release.get("tag_name"))
    require_update(tag.startswith("v"), "release lacks exact tag")
    version = update_version(tag[1:])
    require_update(not target or target == version, "release differs from pinned target")
    require_update(
        release.get("draft") is False and type(release.get("prerelease")) is bool, "release is not published"
    )
    prerelease = "-" in version
    require_update(release["prerelease"] == prerelease, "prerelease identity mismatch")
    require_update(request.get("channel", "stable") == "prerelease" or not prerelease, "prerelease not opted in")
    commit = _release_tag(client, tag)
    require_update(request.get("trustedTargetCommit", commit) == commit, "trusted immutable target changed")
    require_update(
        previous is None or previous["version"] != version or previous["sourceCommit"] == commit,
        "previously observed tag changed",
    )
    assets = {"plugin": _plugin_asset(release, version), **_python_assets(client, version)}
    _source_versions(client, commit, version)
    descriptor, descriptor_status = _impact(client, commit, version)
    return {
        "version": version,
        "tag": tag,
        "sourceCommit": commit,
        "source": UPDATE_SOURCE,
        "publication": assets,
        "releaseImpact": descriptor,
        "descriptorStatus": descriptor_status,
        "publicationStatus": "METADATA_COHERENT_CONTENT_UNVERIFIED",
        "installationReady": False,
    }


def _cache_candidate(cache: dict[str, Any], request: dict[str, Any]) -> dict[str, Any] | None:
    validate_update_cache(cache)
    require_update(cache["policyDigest"] == canonical_digest(request), "cache policy changed")
    if cache["candidate"] is None:
        return None
    candidate = update_object(
        cache["candidate"],
        {
            "version",
            "tag",
            "sourceCommit",
            "source",
            "publication",
            "releaseImpact",
            "descriptorStatus",
            "publicationStatus",
            "installationReady",
        },
        {
            "version",
            "tag",
            "sourceCommit",
            "source",
            "publication",
            "releaseImpact",
            "descriptorStatus",
            "publicationStatus",
            "installationReady",
        },
    )
    version = update_version(candidate["version"])
    require_update(
        candidate["source"] == UPDATE_SOURCE
        and candidate["tag"] == "v" + version
        and candidate["installationReady"] is False,
        "cache cannot authorize installation",
    )
    update_digest(candidate["sourceCommit"], 40)
    require_update(
        request.get("trustedTargetCommit", candidate["sourceCommit"]) == candidate["sourceCommit"],
        "cached immutable target changed",
    )
    if candidate["releaseImpact"] is not None:
        validate_release_impact(candidate["releaseImpact"])
    _cached_target_identity(candidate, request)
    return candidate


def _cached_target_identity(candidate: dict[str, Any], request: dict[str, Any]) -> None:
    version = candidate["version"]
    target = request.get("targetVersion") or (request.get("pin") or "")[1:]
    require_update(not target or version == target, "cache differs from exact target/pin")
    require_update(
        request.get("channel", "stable") == "prerelease" or "-" not in version, "cached prerelease is not opted in"
    )
    descriptor = candidate["releaseImpact"]
    if descriptor is not None:
        require_update(
            descriptor["version"] == version and descriptor["sourceCommit"] in (None, candidate["sourceCommit"]),
            "cached descriptor source/version mismatch",
        )
    require_update(
        candidate["publicationStatus"] == "METADATA_COHERENT_CONTENT_UNVERIFIED", "unsupported cached publication claim"
    )
    publication = update_object(
        candidate["publication"], {"plugin", "bdist_wheel", "sdist"}, {"plugin", "bdist_wheel", "sdist"}
    )
    names = {
        "plugin": "agent-lifecycle-kit-agent-plugin-v" + version + ".zip",
        "bdist_wheel": "agent_lifecycle_kit-" + version + "-py3-none-any.whl",
        "sdist": "agent_lifecycle_kit-" + version + ".tar.gz",
    }
    for kind, entry in publication.items():
        row = update_object(entry, {"filename", "url", "sha256", "bytes"}, {"filename", "url", "sha256", "bytes"})
        _asset({"filename": row["filename"], "size": row["bytes"]}, names[kind], row["url"], row["sha256"])
        parsed = urlsplit(update_text(row["url"]))
        require_update(
            parsed.scheme == "https" and not parsed.query and not parsed.fragment, "invalid cached artifact locator"
        )
        if kind == "plugin":
            expected = UPDATE_SOURCE + "/releases/download/v" + version + "/" + names[kind]
            require_update(row["url"] == expected, "cached plugin origin/target mismatch")
        else:
            require_update(
                parsed.netloc == "files.pythonhosted.org" and parsed.path.endswith("/" + names[kind]),
                "cached Python origin/target mismatch",
            )


def _cached_check(
    request: dict[str, Any], cache: dict[str, Any], timestamp: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    previous = _cache_candidate(cache, request)
    observed = cache["observedAt"]
    attempt = cache.get("lastAttemptAt", observed)
    require_update(attempt <= timestamp, "cache attempt is from the future")
    require_update(observed is None or observed <= timestamp, "cache observation is from the future")
    age = None if observed is None else timestamp - observed
    if timestamp - attempt >= CACHE_CADENCE_SECONDS:
        return previous, None
    if "lastFailureReason" in cache:
        return previous, update_report(
            "check",
            "STALE" if age is not None and age >= CACHE_TTL_SECONDS else "UNAVAILABLE",
            request,
            {
                "reason": cache["lastFailureReason"],
                "lastSuccess": previous,
                "cache": cache,
                "ageSeconds": age,
                "provenance": "CACHED_LOCAL_RECORD",
                "networkRequests": 0,
                "cacheUpdated": False,
            },
        )
    require_update(previous is not None, "cached success unavailable")
    cached_candidate = cast(dict[str, Any], previous)
    status = "CURRENT" if cached_candidate["version"] == agent_lifecycle.__version__ else "AVAILABLE"
    return previous, update_report(
        "check",
        status,
        request,
        {
            "candidate": previous,
            "ageSeconds": age,
            "provenance": "CACHED_LOCAL_RECORD",
            "networkRequests": 0,
            "cacheUpdated": False,
        },
    )


def check_plugin_updates(
    request: dict[str, Any],
    *,
    cache: dict[str, Any] | None = None,
    client: UpdateMetadataClient | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Explicit check only; cache supplied by the caller, no hidden startup hook."""
    validate_update_request(request)
    mode = request.get("mode", "manual")
    if mode == "off":
        return update_report("check", "OFF", request, {"networkRequests": 0, "cacheUpdated": False})
    if mode in ("notify", "safe-auto"):
        return update_report(
            "check",
            "UNSUPPORTED",
            request,
            {"reason": "No qualified trigger/safe-auto route", "networkRequests": 0, "cacheUpdated": False},
        )
    if request.get("channel") == "prerelease" and not (request.get("targetVersion") or request.get("pin")):
        return update_report(
            "check",
            "UNSUPPORTED",
            request,
            {"reason": "UNSUPPORTED_QUERY: exact prerelease required", "networkRequests": 0, "cacheUpdated": False},
        )
    timestamp = int(time.time()) if now is None else now
    require_update(type(timestamp) is int and 0 <= timestamp <= 4102444800, "invalid observation time")
    previous = None
    if cache is not None:
        previous, replay = _cached_check(request, cache, timestamp)
        if replay is not None:
            return replay
    transport = client or UpdateMetadataClient()
    try:
        candidate = _discover(request, transport, previous)
    except (LifecycleError, OSError, ValueError, TypeError) as exc:
        if isinstance(exc, LifecycleError):
            reason = exc.code if exc.code in UPDATE_FAILURE_REASONS else "plugin-update-metadata-unavailable"
        else:
            reason = (
                "plugin-update-network-unavailable" if isinstance(exc, OSError) else "plugin-update-metadata-invalid"
            )
        observed = cache["observedAt"] if cache is not None else None
        stale = observed is not None and timestamp - observed >= CACHE_TTL_SECONDS
        failed_cache = validate_update_cache(
            {
                "schemaVersion": UPDATE_CACHE_SCHEMA,
                "policyDigest": canonical_digest(request),
                "observedAt": observed,
                "candidate": previous,
                "lastAttemptAt": timestamp,
                "lastFailureReason": reason,
            }
        )
        return update_report(
            "check",
            "STALE" if stale else "UNAVAILABLE",
            request,
            {
                "reason": reason,
                "lastSuccess": previous,
                "cache": failed_cache,
                **transport.usage(),
                "cacheUpdated": True,
            },
        )
    cached = validate_update_cache(
        {
            "schemaVersion": UPDATE_CACHE_SCHEMA,
            "policyDigest": canonical_digest(request),
            "observedAt": timestamp,
            "lastAttemptAt": timestamp,
            "candidate": candidate,
        }
    )
    status = "CURRENT" if candidate["version"] == agent_lifecycle.__version__ else "AVAILABLE"
    return update_report(
        "check",
        status,
        request,
        {
            "candidate": candidate,
            "cache": cached,
            "cacheUpdated": True,
            **transport.usage(),
            "provenance": "OBSERVED_OFFICIAL_METADATA",
        },
    )


def store_update_cache(root: Path, name: str, value: dict[str, Any], *, inputs: tuple[str, ...] = ()) -> None:
    """Only replace a valid cache, never an input or existing non-cache record."""
    validate_update_cache(value)
    from agent_lifecycle.contracts import normalize_repo_path

    normalized = normalize_repo_path(name)
    require_update(normalized not in inputs, "cache aliases an input")
    require_update(normalized.split("/")[0].casefold() not in UPDATE_FORBIDDEN_ROOTS, "unsafe cache scope")
    require_update(
        not normalized.casefold().endswith((".state.json", ".lock.json", "plan.manifest.json")),
        "cache cannot use an authority filename",
    )
    path = root / normalized
    data = canonical_bytes(value) + b"\n"
    if path.exists() or path.is_symlink():
        validate_update_cache(read_update_json(root, normalized))
        replace_authority_bytes(path, data, root=root)
    else:
        create_authority_bytes(path, data, root=root, private=True)
