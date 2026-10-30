"""Host entrypoint for bounded, authority-pinned journal maintenance.

The bridge uses the existing retention implementation. It neither attests
provider usage nor grants model dispatch or a protected operator boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
import weakref
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, NoReturn
from typing import cast as _validated_cast

from agent_lifecycle.accounting.profile_schema import matches_profile_schema
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import (
    hold_authority_directory,
    open_authority_read,
    read_authority_bytes,
)
from agent_lifecycle.contracts.paths import normalize_repo_path

from .closing_resources import (
    JournalRetentionMixin,
    _raw_parent,
    _raw_private_file,
    _raw_read,
    _raw_ref,
    _raw_stat,
)
from .contracts import EvidenceRef, JournalUnavailable, canonical, digest, utc_instant
from .journal import Journal
from .support_profiles import match_requested_claims, validate_profile_payload

PROFILE_BYTES = 262_144
ARTIFACT_BYTES = 8_388_608
TASK_BYTES = 25_165_824
MAX_REFS = 64
MAX_DEPTH = 8
_REF_KEYS = {"path", "sha256", "bytes"}
_CEILING_KEYS = ("dimension", "guarantee", "unitId", "limitKind", "boundMethodId")


def _fail(code: str) -> NoReturn:
    raise LifecycleError(code, "Accounting profile input check refused")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _fail("accounting-json-duplicate-key")
        value[key] = item
    return value


def decode_json_object(raw: bytes) -> dict[str, Any]:
    """Decode raw accounting JSON with the existing strict object/error contract."""
    try:
        value = json.loads(
            raw, object_pairs_hook=_no_duplicates, parse_constant=lambda _value: _fail("accounting-json-invalid")
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LifecycleError("accounting-json-invalid", "Accounting input is invalid JSON") from exc
    if not isinstance(value, dict):
        _fail("accounting-json-not-object")
    return value


_json = decode_json_object


class BoundedReader:
    """One immutable input snapshot and a shared conservative content-read budget."""

    def __init__(self, limit: int = TASK_BYTES) -> None:
        self.limit = limit
        self.charged_bytes = 0
        self.cache: dict[tuple[str, str], bytes] = {}
        self.roots: dict[str, int] = {}
        self.root_guards: dict[str, ExitStack] = {}
        self.finalizer = weakref.finalize(self, self._close_roots, self.roots, self.root_guards)

    @staticmethod
    def _close_roots(roots: dict[str, int], guards: dict[str, ExitStack]) -> None:
        for fd in roots.values():
            if fd >= 0:
                with suppress(OSError):
                    os.close(fd)
        roots.clear()
        for guard in guards.values():
            guard.close()
        guards.clear()

    def close(self) -> None:
        self.finalizer()

    def snapshot_refs(self, root: Path) -> list[dict]:
        """Expose the bytes actually read, normalized to one repository root."""
        refs: dict[str, dict] = {}
        for (source_root, path), raw in self.cache.items():
            relative = (Path(source_root) / path).relative_to(root.absolute()).as_posix()
            ref = {"path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            if relative in refs and refs[relative] != ref:
                _fail("accounting-snapshot-reference-conflict")
            refs[relative] = ref
        return [refs[path] for path in sorted(refs)]

    def _root(self, root: Path) -> tuple[str, int]:
        if not self.finalizer.alive:
            _fail("accounting-reader-closed")
        # The caller supplies a canonical absolute root. Never resolve a mutable
        # root name to another directory; pin its original directory descriptor.
        absolute_root = root.absolute()
        key = str(absolute_root)
        if key in self.roots:
            return key, self.roots[key]
        if os.name == "nt":
            guard = ExitStack()
            try:
                guard.enter_context(hold_authority_directory(absolute_root))
            except BaseException:
                guard.close()
                raise
            self.root_guards[key] = guard
            self.roots[key] = -1  # Windows uses held HANDLE guards, never a POSIX fd.
            return key, -1
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        parent = os.open(absolute_root.anchor, flags)
        try:
            for part in absolute_root.parts[1:]:
                if part == "..":
                    _fail("accounting-artifact-path-invalid")
                child = os.open(part, flags, dir_fd=parent)
                os.close(parent)
                parent = child
        except (OSError, LifecycleError):
            os.close(parent)
            raise
        self.roots[key] = parent
        return key, parent

    def read(self, root: Path, relative: str, limit: int) -> bytes:
        if normalize_repo_path(relative, label="accounting artifact") != relative:
            _fail("accounting-artifact-path-invalid")
        if os.name != "nt" and not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")):
            _fail("accounting-safe-read-unavailable")
        if os.name != "nt" and os.open not in os.supports_dir_fd:
            _fail("accounting-safe-read-unavailable")
        root_key, root_fd = self._root(root)
        key = (root_key, relative)
        if key in self.cache:
            raw = self.cache[key]
            if len(raw) > limit:
                _fail("accounting-artifact-size-invalid")
            return raw
        if self.charged_bytes >= self.limit:
            _fail("accounting-reference-budget-exceeded")
        if os.name == "nt":
            try:
                with open_authority_read(root / relative, root=root) as stream:
                    raw = self._consume(stream, limit)
            except OSError as exc:
                raise LifecycleError("accounting-artifact-open-refused", "Accounting artifact read refused") from exc
            self.cache[key] = raw
            return raw
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        # Hold every parent while opening its child: a concurrent directory
        # rename cannot redirect a later leaf open through an outside symlink.
        parent = os.dup(root_fd)
        try:
            for part in Path(relative).parts[:-1]:
                child = os.open(part, directory_flags, dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(Path(relative).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb", buffering=0) as stream:
                raw = self._consume(stream, limit)
        except OSError as exc:
            raise LifecycleError("accounting-artifact-open-refused", "Accounting artifact read refused") from exc
        finally:
            os.close(parent)
        self.cache[key] = raw
        return raw

    def _consume(self, stream: BinaryIO, limit: int) -> bytes:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            _fail("accounting-artifact-size-invalid")
        if before.st_size > self.limit - self.charged_bytes:
            _fail("accounting-reference-budget-exceeded")
        # Reserve before IO; failed reads and failed hash checks retain it.
        self.charged_bytes += before.st_size
        raw = stream.read(before.st_size)
        after = os.fstat(stream.fileno())
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, f) != getattr(after, f) for f in fields) or len(raw) != before.st_size:
            _fail("accounting-artifact-changed-during-read")
        return raw


def _read(root: Path, relative: str, limit: int, reader: BoundedReader | None = None) -> bytes:
    return (reader if reader is not None else BoundedReader()).read(root, relative, limit)


def _refs(
    value: Any, depth: int = 0, *, _schema_metadata: bool = False, _schema_definitions: bool = False
) -> list[dict[str, Any]]:
    """Find data references without interpreting schema declarations as data."""
    if depth > 64:
        _fail("accounting-json-depth-exceeded")
    if isinstance(value, dict):
        if not _schema_metadata and set(value) == _REF_KEYS:
            return [value]
        return [
            ref
            for key, item in value.items()
            for ref in _refs(
                item, depth + 1, _schema_metadata=_schema_metadata or (_schema_definitions and key == "$defs")
            )
        ]
    if isinstance(value, list):
        return [ref for item in value for ref in _refs(item, depth + 1, _schema_metadata=_schema_metadata)]
    return []


class EvidenceGraph:
    """Verify bounded static file references; assign no provenance or authority."""

    def __init__(
        self, root: Path, reader: BoundedReader | None = None, *, schema_refs: list[dict[str, Any]] | None = None
    ) -> None:
        if root.is_symlink():
            _fail("accounting-evidence-root-symlink")
        self.root = root
        self.verified: dict[str, dict[str, Any]] = {}
        self.active: set[str] = set()
        self.bytes_read = 0
        self.reader = reader if reader is not None else BoundedReader()
        self.documents: dict[str, dict[str, Any]] = {}
        self.children: dict[str, set[str]] = {}
        self.heights: dict[str, int] = {}
        self.raw_bytes: dict[str, bytes] = {}
        self.refused = False
        # The caller establishes schema identity; data cannot register itself
        # by inserting a dialect marker. Exact raw refs still undergo verification.
        self.schema_refs = tuple(dict(ref) for ref in schema_refs or ())

    def _height(self, path: str, visiting: set[str] | None = None) -> int:
        visiting = visiting if visiting is not None else set()
        if path in visiting:
            _fail("accounting-reference-cycle")
        if path not in self.heights:
            visiting.add(path)
            self.heights[path] = max((1 + self._height(c, visiting) for c in self.children.get(path, set())), default=0)
            visiting.remove(path)
        return self.heights[path]

    def _expand(self, path: str, raw: bytes, depth: int) -> None:
        if path in self.documents:
            return
        document = _json(raw)
        self.active.add(path)
        self.children[path] = set()
        self.heights.clear()
        registered = self.verified[path] in self.schema_refs
        dialect = "https://json-schema.org/draft/2020-12/schema"
        mixed = registered and document.get("schemaDialect") == dialect
        schema = registered and not mixed and document.get("$schema") == dialect
        for child in _refs(document, _schema_metadata=schema, _schema_definitions=mixed):
            self.verify(child, depth + 1)
            self.children[path].add(child["path"])
            self.heights.clear()
        self.active.remove(path)
        self.documents[path] = document

    def document(self, ref: dict[str, Any]) -> dict[str, Any]:
        self.verify(ref, parse_json=True)
        return self.documents[ref["path"]]

    def verify(self, ref: dict[str, Any], depth: int = 0, *, parse_json: bool = False) -> None:
        if self.refused:
            _fail("accounting-graph-already-refused")
        try:
            self._verify(ref, depth, parse_json=parse_json)
        except (LifecycleError, OSError, ValueError, TypeError, KeyError, RecursionError):
            self.refused = True
            raise

    def _verify(self, ref: dict[str, Any], depth: int, *, parse_json: bool) -> None:
        if depth > MAX_DEPTH or not isinstance(ref, dict) or set(ref) != _REF_KEYS:
            _fail("accounting-reference-invalid")
        path, digest, size = ref["path"], ref["sha256"], ref["bytes"]
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or type(size) is not int
            or not 0 <= size <= ARTIFACT_BYTES
        ):
            _fail("accounting-reference-invalid")
        if path in self.active:
            _fail("accounting-reference-cycle")
        if path in self.verified:
            if self.verified[path] != ref:
                _fail("accounting-reference-conflict")
            if parse_json and path not in self.documents:
                self._expand(path, self.raw_bytes[path], depth)
            if depth + self._height(path) > MAX_DEPTH:
                _fail("accounting-reference-invalid")
            return
        if len(self.verified) >= MAX_REFS or self.bytes_read + size > TASK_BYTES:
            _fail("accounting-reference-budget-exceeded")
        raw = _read(self.root, path, ARTIFACT_BYTES, self.reader)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            _fail("accounting-reference-digest-mismatch")
        self.bytes_read += size
        self.verified[path] = dict(ref)
        self.raw_bytes[path] = raw
        if parse_json or path.endswith(".json"):
            self._expand(path, raw, depth)
        if depth + self._height(path) > MAX_DEPTH:
            _fail("accounting-reference-invalid")


def _candidate_sources(reader: BoundedReader, root: Path) -> list[dict]:
    """Fingerprint current ALK Python source; never let a report select its files."""
    _, anchor = reader._root(root)
    flags = 0 if os.name == "nt" else os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    paths: list[str] = []
    entries_seen = 0

    def visit(fd: int | Path, prefix: str, depth: int) -> None:
        nonlocal entries_seen
        if depth > 64:
            _fail("accounting-source-inventory-overflow")
        with os.scandir(fd) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > 8192:
                    _fail("accounting-source-inventory-overflow")
                if entry.name == "__pycache__":
                    continue
                relative = prefix + "/" + entry.name
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    _fail("accounting-source-symlink")
                if stat.S_ISDIR(info.st_mode):
                    if isinstance(fd, Path):
                        child_path = fd / entry.name
                        with hold_authority_directory(child_path):
                            visit(child_path, relative, depth + 1)
                    else:
                        child = os.open(entry.name, flags, dir_fd=fd)
                        try:
                            visit(child, relative, depth + 1)
                        finally:
                            os.close(child)
                elif relative.endswith(".py"):
                    if not stat.S_ISREG(info.st_mode) or len(paths) >= 4096:
                        _fail("accounting-source-inventory-overflow")
                    paths.append(relative)

    if os.name == "nt":
        with hold_authority_directory(root / "src"):
            visit(root / "src", "src", 0)
    else:
        src = os.open("src", flags, dir_fd=anchor)
        try:
            visit(src, "src", 0)
        finally:
            os.close(src)
    paths.append("tools/release/validate_accounting_adapter_profiles.py")
    rows = []
    for path in sorted(set(paths)):
        raw = reader.read(root, path, ARTIFACT_BYTES)
        rows.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    if len(rows) < 2:
        _fail("accounting-source-inventory-empty")
    return rows


def _profile_schema(value: dict, definitions: dict, name: str) -> None:
    if not matches_profile_schema(value, definitions, name):
        _fail("accounting-qualification-schema-invalid")


def _source_qualification_authority(reader: BoundedReader, repo_root: Path) -> tuple[dict, dict, dict, dict]:
    """Read and verify the existing frozen H04 authorities before profile data."""
    authority_refs = {}
    authority = {}
    for name in (
        "plan.manifest.json",
        "plan.lock.json",
        "h04-artifact-contracts.json",
        "h04-adapter-profile-cases.json",
    ):
        path = "tasks/release-2-16/" + name
        raw_authority = reader.read(repo_root, path, ARTIFACT_BYTES)
        authority_refs[name] = {
            "path": path,
            "sha256": hashlib.sha256(raw_authority).hexdigest(),
            "bytes": len(raw_authority),
        }
        authority[name] = _json(raw_authority)
    manifest, lock = authority["plan.manifest.json"], authority["plan.lock.json"]
    contracts, expected = authority["h04-artifact-contracts.json"], authority["h04-adapter-profile-cases.json"]
    if manifest.get("status") != "FROZEN":
        _fail("accounting-plan-not-frozen")
    if lock.get("manifestHash") != digest(manifest):
        _fail("accounting-frozen-authority-mismatch")
    if not isinstance(lock.get("entries"), list) or any(not isinstance(row, dict) for row in lock["entries"]):
        _fail("accounting-frozen-authority-mismatch")
    for name in ("h04-artifact-contracts.json", "h04-adapter-profile-cases.json"):
        ref = authority_refs[name]
        pinned = [row for row in lock["entries"] if row.get("path") == ref["path"]]
        if pinned != [ref]:
            _fail("accounting-frozen-authority-mismatch")
    return authority_refs, manifest, contracts, expected


def _validate_source_qualification_observations(
    qualification: dict, payload: dict, entry: dict, sources: dict, roles: dict
) -> None:
    observations = {o["observationId"]: o for o in qualification["observations"]}
    if len(observations) != len(qualification["observations"]):
        _fail("accounting-qualification-observation-duplicate")
    for observation in observations.values():
        if (
            observation["kind"] != "DOCUMENTED_LIMITATION"
            or observation["claimIds"]
            or observation["actualBinding"] != payload["binding"]
            or observation["usageStatus"] != "UNAVAILABLE"
            or observation["usage"] is not None
            or observation["priorPermitRef"] is not None
            or observation["reuseApplicabilityRef"] is not None
            or observation["recipeId"] != entry["qualificationRecipe"]["recipeId"]
            or set(observation["sourceIds"]) - set(sources)
            or set(observation["routeIds"]) - set(roles)
        ):
            _fail("accounting-source-observation-invalid")
    dispositions = {d["candidateId"]: d for d in qualification["candidateDispositions"]}
    candidates = entry["candidateRequirements"]
    if len(dispositions) != len(qualification["candidateDispositions"]) or set(dispositions) != {
        c["candidateId"] for c in candidates
    }:
        _fail("accounting-qualification-candidate-inventory-invalid")
    for candidate in candidates:
        disposition = dispositions[candidate["candidateId"]]
        selected_observations = [observations.get(oid) for oid in disposition["observationIds"]]
        if (
            disposition["disposition"] not in {"QUALIFIED_LIMITATION", "REVIEWED_EXCLUSION"}
            or disposition["claimIds"]
            or not selected_observations
            or any(o is None for o in selected_observations)
            or any(_validated_cast(dict, o)["unitId"] != candidate["unitId"] for o in selected_observations)
            or not set(candidate["sourceIds"])
            <= {sid for o in selected_observations for sid in _validated_cast(dict, o)["sourceIds"]}
        ):
            _fail("accounting-qualification-candidate-unresolved")


def _read_final_source_qualification_data(
    final: bool,
    reader: BoundedReader,
    profiles_root: Path,
    adapter_id: str,
    contracts: dict,
    payload: dict,
    checked: dict,
    qref: dict,
    graph: EvidenceGraph,
    joins: dict,
    prefix: str,
) -> dict:
    final_data = {}
    if final:
        profile_raw = reader.read(profiles_root, adapter_id + "/profile.json", PROFILE_BYTES)
        envelope = _json(profile_raw)
        _profile_schema(envelope, contracts["$defs"], "profile")
        if (
            envelope["payload"] != payload
            or envelope["profileDigest"] != checked["profileDigest"]
            or envelope["qualificationRef"] != qref
            or envelope["resolverEvidenceRef"]["path"] != adapter_id + "/resolver-evidence.json"
        ):
            _fail("accounting-final-profile-binding-mismatch")
        resolver = graph.document(envelope["resolverEvidenceRef"])
        _profile_schema(resolver, contracts["$defs"], "resolverEvidence")
        if any(
            resolver[key] != joins[key]
            for key in ("profileDigest", "expectationDigest", "planDigest", "alkCandidateDigest")
        ):
            _fail("accounting-resolver-evidence-binding-mismatch")
        producer = next(p for p in contracts["producers"] if p["id"] == "P-EXACT-PROFILE-RESOLVER")
        if resolver["commandDigest"] != digest(producer["command"]):
            _fail("accounting-resolver-command-mismatch")
        ids = [row["caseId"] for row in resolver["observations"]]
        if len(ids) != len(set(ids)):
            _fail("accounting-resolver-observation-duplicate")
        for ref in _refs(envelope):
            graph.verify(ref)
        final_data = {
            "profile": envelope,
            "resolver": resolver,
            "resolverReceipt": graph.document(resolver["receiptRef"]),
            "resolverTraces": {
                row["rawTraceRef"]["path"]: graph.document(row["rawTraceRef"]) for row in resolver["observations"]
            },
        }
        resolver_subject_path = adapter_id + "/resolver-subject.json"
        resolver_subject_raw = reader.read(profiles_root, resolver_subject_path, PROFILE_BYTES)
        resolver_projection = {
            "schemaVersion": "alk-accounting-resolver-subject.v1",
            "resolverDigest": digest({k: v for k, v in resolver.items() if k != "receiptRef"}),
        }
        if _json(resolver_subject_raw) != resolver_projection:
            _fail("accounting-resolver-subject-mismatch")
        final_data["resolverSubjectRef"] = {
            "path": prefix + "/" + resolver_subject_path,
            "sha256": hashlib.sha256(resolver_subject_raw).hexdigest(),
            "bytes": len(resolver_subject_raw),
        }
    return final_data


def _read_source_lifecycle_qualification(
    reader: BoundedReader,
    repo_root: Path,
    profiles_root: Path,
    adapter_id: str,
    *,
    final: bool,
) -> dict:
    prefix = profiles_root.absolute().relative_to(repo_root.absolute()).as_posix()
    normalize_repo_path(prefix, label="profiles root")
    authority_refs, manifest, contracts, expected = _source_qualification_authority(reader, repo_root)
    entries = expected["expectedBindings"]["entries"]
    selected = [entry for entry in entries if entry["adapterId"] == adapter_id]
    if len(selected) != 1:
        _fail("accounting-expectation-unavailable")
    entry = selected[0]
    payload = _json(reader.read(profiles_root, adapter_id + "/profile-payload.json", PROFILE_BYTES))
    checked = validate_profile_payload(payload)
    if (
        payload["expectationId"] != entry["expectationId"]
        or payload["binding"]["adapterId"] != adapter_id
        or payload["binding"]["hostVersion"] != entry["target"]["version"]
    ):
        _fail("accounting-profile-binding-mismatch")
    if (
        payload["binding"]["evidenceMode"] != "SOURCE_BOUND_LIMITATION"
        or payload["modes"] != ["LIFECYCLE_ONLY"]
        or payload["claims"]
        or payload["completeFinancialRun"]
    ):
        _fail("accounting-qualified-mode-unavailable")
    roles = {rid: rid.split(".")[0] for rid in entry["roleInventory"]}
    if {r["routeId"]: r["role"] for r in payload["routes"]} != roles or any(
        r["state"] != "EXCLUDED" for r in payload["routes"]
    ):
        _fail("accounting-qualified-route-inventory-invalid")
    cases = {r["sourceCaseId"]: r["sourceCaseSha256"] for r in entry["sourceCaseRequirements"]}
    if {r["sourceCaseId"]: r["sourceCaseSha256"] for r in payload["sourceCaseDispositions"]} != cases or any(
        r["disposition"] not in {"QUALIFIED_LIMITATION", "NOT_APPLICABLE_TO_SELECTED_GUARANTEE"}
        for r in payload["sourceCaseDispositions"]
    ):
        _fail("accounting-qualified-source-cases-unresolved")
    sources = {s["sourceId"]: s for s in payload["sources"]}
    if set(sources) != {s["sourceId"] for s in entry["sources"]}:
        _fail("accounting-qualified-source-inventory-invalid")
    graph = EvidenceGraph(profiles_root, reader, schema_refs=[authority_refs["h04-artifact-contracts.json"]])
    for frozen in entry["sources"]:
        source = sources[frozen["sourceId"]]
        # Frozen capture kinds and payload source kinds use different
        # vocabularies. Archive bytes prove a source-bound input, not a
        # current runtime observation or an independent review publication.
        origins = frozen["origins"] or [frozen["artifact"]["path"]]
        if (
            source["kind"] in {"RUNTIME_OBSERVATION", "INDEPENDENT_REVIEW"}
            or source["origin"] not in origins
            or source["versionApplicability"] != entry["target"]["version"]
            or any(source["artifact"][k] != frozen["artifact"][k] for k in ("sha256", "bytes"))
        ):
            _fail("accounting-qualified-source-binding-invalid")
        original = reader.read(repo_root, frozen["artifact"]["path"], ARTIFACT_BYTES)
        if (
            len(original) != frozen["artifact"]["bytes"]
            or hashlib.sha256(original).hexdigest() != frozen["artifact"]["sha256"]
        ):
            _fail("accounting-frozen-source-changed")
    raw = reader.read(profiles_root, adapter_id + "/qualification.json", ARTIFACT_BYTES)
    qref = {"path": adapter_id + "/qualification.json", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    qualification = graph.document(qref)
    _profile_schema(qualification, contracts["$defs"], "qualification")
    for ref in _refs(payload):
        graph.verify(ref)
    candidate_rows = _candidate_sources(reader, repo_root)
    candidate_digest = digest(candidate_rows)
    joins = {
        "profileDigest": checked["profileDigest"],
        "expectationDigest": digest(entry),
        "planDigest": digest(manifest),
        "alkCandidateDigest": candidate_digest,
        "binding": payload["binding"],
    }
    if any(qualification[key] != value for key, value in joins.items()):
        _fail("accounting-qualification-binding-mismatch")
    _validate_source_qualification_observations(qualification, payload, entry, sources, roles)
    subject_path = adapter_id + "/qualification-subject.json"
    subject_raw = reader.read(profiles_root, subject_path, PROFILE_BYTES)
    projection = {
        "schemaVersion": "alk-accounting-qualification-subject.v1",
        "profileDigest": checked["profileDigest"],
        "qualificationDigest": digest({k: v for k, v in qualification.items() if k != "reviewEvidenceRef"}),
    }
    if _json(subject_raw) != projection:
        _fail("accounting-qualification-review-subject-mismatch")
    subject_ref = {
        "path": prefix + "/" + subject_path,
        "sha256": hashlib.sha256(subject_raw).hexdigest(),
        "bytes": len(subject_raw),
    }
    review = graph.document(qualification["reviewEvidenceRef"])
    final_data = _read_final_source_qualification_data(
        final, reader, profiles_root, adapter_id, contracts, payload, checked, qref, graph, joins, prefix
    )
    return {
        **final_data,
        "payload": payload,
        "qualification": qualification,
        "review": review,
        "reviewRef": qualification["reviewEvidenceRef"],
        "joins": joins,
        "subjectRef": subject_ref,
        "authorityRefs": authority_refs,
        "contentDigest": digest(
            {
                "payload": payload,
                "qualification": qualification,
                "authorityRefs": authority_refs,
                "subjectRef": subject_ref,
                "finalData": final_data,
                "candidateSources": candidate_rows,
                "refs": sorted(graph.verified.values(), key=lambda r: r["path"]),
            }
        ),
        "readBytes": reader.charged_bytes,
    }


def read_source_lifecycle_qualifications(
    repo_root: Path,
    profiles_root: Path,
    adapter_ids: list[str],
    *,
    byte_limit: int = TASK_BYTES,
    final: bool = False,
) -> dict:
    """Read a batch with one immutable cache/budget; never grant authority."""
    if (
        not isinstance(adapter_ids, list)
        or not 1 <= len(adapter_ids) <= 12
        or len(set(adapter_ids)) != len(adapter_ids)
    ):
        _fail("accounting-profile-batch-invalid")
    reader = BoundedReader(byte_limit)
    try:
        profiles = {
            adapter: _read_source_lifecycle_qualification(reader, repo_root, profiles_root, adapter, final=final)
            for adapter in adapter_ids
        }
        return {
            "profiles": profiles,
            "readBytes": reader.charged_bytes,
            "snapshotRefs": reader.snapshot_refs(repo_root),
        }
    finally:
        reader.close()


def read_source_lifecycle_qualification(
    repo_root: Path,
    profiles_root: Path,
    adapter_id: str,
    *,
    byte_limit: int = TASK_BYTES,
) -> dict:
    """Read staged contents; the upper layer must verify actual observed review.

    This does not accept a final profile or grant dispatch. The batch reader
    also supports final envelope/resolver content for the offline validator.
    """
    batch = read_source_lifecycle_qualifications(repo_root, profiles_root, [adapter_id], byte_limit=byte_limit)
    return {**batch["profiles"][adapter_id], "readBytes": batch["readBytes"]}


CAPABILITY_UNAVAILABLE = "ADAPTER_BUDGET_CAPABILITY_UNAVAILABLE"


def read_accounting_input(path: Path) -> dict:
    """Read a bounded closed JSON object without treating it as authority."""
    try:
        return _read_object(read_authority_bytes(path, max_bytes=262_144))
    except (LifecycleError, ValueError, OSError, RecursionError) as exc:
        raise LifecycleError(CAPABILITY_UNAVAILABLE, "Accounting capability input is unavailable") from exc


def accounting_request_blocker() -> dict:
    """No accepted qualification consumer exists yet; never trust a caller permit.

    This guard applies whenever an accounting capability is explicitly requested,
    including malformed requests and supplied ALLOW/PASS results. Ordinary launch
    without an accounting request keeps its existing lifecycle/launch gates.
    """
    return {"code": CAPABILITY_UNAVAILABLE, "detail": "UNQUALIFIED_EVIDENCE"}


def resolve_accounting_capability(
    profile: dict,
    request: dict,
    *,
    expectation_digest: str,
    plan_digest: str,
    candidate_digest: str,
) -> dict:
    """Return exact structural refusals, never promote pending evidence to ALLOW.

    This is the refusal side of the resolver, not the completed qualification
    consumer. Its independent authority inputs are not certified here. Even a
    structural MATCH therefore remains DENY until that consumer is implemented.
    """
    try:
        request_digest = digest(request)
        if (
            not isinstance(profile, dict)
            or set(profile) != {"schemaVersion", "payload", "profileDigest", "qualificationRef", "resolverEvidenceRef"}
            or profile["schemaVersion"] != "alk-accounting-profile.v1"
        ):
            raise ValueError("Closed profile envelope required")
        payload = profile["payload"]
        profile_digest = digest(payload)
        if profile["profileDigest"] != profile_digest:
            raise ValueError("Profile digest mismatch")
        matched = match_requested_claims(
            payload,
            request,
            expectation_digest=expectation_digest,
            plan_digest=plan_digest,
            candidate_digest=candidate_digest,
        )
        detail = matched["detail"] if matched["status"] == "MISMATCH" else "UNQUALIFIED_EVIDENCE"
        if matched["status"] == "MATCH_PENDING_EVIDENCE" and (
            request["requestedModes"] != ["LIFECYCLE_ONLY"] or request["requiredClaims"]
        ):
            # Positive requests cover the entire named operation, including
            # routes not repeated inside a narrower individual claim. MATCH00
            # permits ordinary lifecycle-only requests without financial claims.
            routes = {row["routeId"]: row for row in payload["routes"]}
            if any(routes[rid]["state"] != "COVERED" for rid in request["routeIds"]):
                detail = "UNCOVERED_ROUTE"
    except (LifecycleError, ValueError, TypeError, RecursionError, KeyError):
        # An invalid object cannot contribute an authoritative binding. These
        # digests identify a fixed invalid-input marker, never an accepted input.
        request_digest = profile_digest = digest({"invalidInput": True})
        detail = "INVALID_INPUT"
    if (
        not isinstance(expectation_digest, str)
        or len(expectation_digest) != 64
        or any(char not in "0123456789abcdef" for char in expectation_digest)
    ):
        expectation_digest = digest({"invalidExpectation": True})
        detail = "INVALID_INPUT"
    return {
        "schemaVersion": "alk-accounting-capability-result.v1",
        "requestDigest": request_digest,
        "profileDigest": profile_digest,
        "expectationDigest": expectation_digest,
        "outcome": "DENY",
        "reason": CAPABILITY_UNAVAILABLE,
        "detail": detail,
        "matchedClaimIds": [],
        "dispatchEntitlement": False,
    }


class _MaintenanceJournal(Journal):
    """Carry the original invocation deadline through initial writer admission."""

    def __init__(self, path, writer, *, storage_version: int, stop: float, deadline_utc: str):
        self._original_stop = stop
        self._original_utc_deadline = utc_instant(deadline_utc)
        self._require_time()
        super().__init__(path, writer, storage_version=storage_version)

    def _require_time(self) -> None:
        if datetime.now(UTC) >= self._original_utc_deadline or time.monotonic() >= self._original_stop:
            raise JournalUnavailable("Original maintenance deadline exhausted", write_outcome="NOT_STARTED")

    @contextmanager
    def _write_admission(self):
        self._require_time()
        # Journal.__init__ clears this field before its first admission. Restore
        # the same original stop here so the existing queue also gets that limit.
        self._maintenance_deadline = self._original_stop
        with super()._write_admission():
            self._require_time()
            yield


def _require_raw_platform() -> None:
    if os.name == "nt":
        # The selected private Windows context checks real ACLs and flushes;
        # a platform label alone does not authorize any deletion.
        return
    if (
        os.name != "posix"
        or not getattr(os, "O_NOFOLLOW", 0)
        or not getattr(os, "O_DIRECTORY", 0)
        or any(fn not in os.supports_dir_fd for fn in (os.open, os.stat, os.link, os.unlink))
        or os.link not in os.supports_follow_symlinks
    ):
        raise LifecycleError("retention-platform-unsupported", "Safe private raw maintenance is unavailable")


def _read_object(raw: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate authority member")
            value[key] = item
        return value

    value = json.loads(
        raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite authority"))
    )
    if not isinstance(value, dict):
        raise ValueError("Authority object required")
    canonical(value)
    return value


def _open_authority(path: Path, expected_sha: str) -> tuple[Path, dict, dict, EvidenceRef]:
    if (
        not path.is_absolute()
        or path.resolve(strict=True) != path
        or not isinstance(expected_sha, str)
        or len(expected_sha) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha)
    ):
        raise ValueError("Canonical absolute authority and SHA-256 required")
    root = path.parent
    with _raw_parent(root, path.name) as (parent, name):
        raw, _ = _raw_read(parent, name, maximum=1_048_576)
        writer_raw, _ = _raw_read(parent, name + ".writer.json", maximum=4096)
    ref = {"path": path.name, "sha256": expected_sha, "bytes": len(raw)}
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Maintenance authority SHA mismatch")
    authority = _read_object(raw)
    writer_data = _read_object(writer_raw)
    if set(writer_data) != {"ref", "digest"}:
        raise ValueError("Closed writer reference required")
    writer = EvidenceRef(**writer_data)
    if digest(asdict(writer)) != authority.get("writerDigest"):
        raise ValueError("Pinned maintenance writer mismatch")
    # Reuse the journal's complete root/file/plan/lock validator on a read-only
    # connection before the writable Journal constructor can touch the database.
    with _raw_parent(root, _validated_cast(str, authority.get("journalPath"))) as (parent, name):
        info = _raw_stat(parent, name)
        if (
            not stat.S_ISREG(info.st_mode)
            or not _raw_private_file(parent, name, info)
            or info.st_nlink != 1
            or authority.get("journalFileIdentity") != {"device": info.st_dev, "inode": info.st_ino}
        ):
            raise ValueError("Pinned journal file changed")
    journal_path = root / authority["journalPath"]
    db = sqlite3.connect(journal_path.as_uri() + "?mode=ro", uri=True)
    try:
        identity = db.execute("SELECT journal_id FROM retention_metadata WHERE singleton=1").fetchone()[0]
        version = db.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()[0]
        probe = SimpleNamespace(_path=journal_path, writer=writer, _storage_version=version, journal_identity=identity)
        JournalRetentionMixin._raw_authority(_validated_cast(JournalRetentionMixin, probe), root, ref)
    finally:
        db.close()
    return root, authority, ref, writer


def _pending_runs(journal: Journal, limit: int) -> list[str]:
    # Already collected SQL detail must not hide still-pending raw obligations.
    rows = journal._db.execute(
        "SELECT DISTINCT r.scope FROM maintenance_receipts r "
        "LEFT JOIN run_closures c ON c.key=r.scope "
        "WHERE r.owner='raw-obligation' AND NOT EXISTS "
        "(SELECT 1 FROM maintenance_receipts d WHERE d.key='raw-done:'||r.digest) "
        "ORDER BY EXISTS(SELECT 1 FROM financial_exceptions e WHERE e.scope=r.scope), "
        "c.key IS NULL, json_extract(c.payload,'$.eligible_after'),r.scope LIMIT ?",
        (limit,),
    ).fetchall()
    return [row[0] for row in rows]


def _next_pending_due(journal: Journal) -> str | None:
    row = journal._db.execute(
        "SELECT r.scope FROM maintenance_receipts r JOIN run_closures c ON c.key=r.scope "
        "WHERE r.owner='raw-obligation' AND NOT EXISTS "
        "(SELECT 1 FROM maintenance_receipts d WHERE d.key='raw-done:'||r.digest) "
        "ORDER BY json_extract(c.payload,'$.eligible_after'),r.scope LIMIT 1"
    ).fetchone()
    return _validated_cast(dict, journal.closed_run(row[0]))["eligible_after"] if row else None


def maintain_raw_details(
    authority_path: Path,
    authority_sha: str,
    *,
    candidate_limit: int,
    deadline_utc: str,
) -> dict:
    """Delete eligible closed-run details; retain summaries, dedup and open runs.

    The root is the canonical authority's parent. Its private writer sidecar
    supplies the reference pinned by writerDigest, including after SQL cleanup.
    There is no caller override for the root, database, clock or retention age.
    """
    _require_raw_platform()
    started = datetime.now(UTC)
    try:
        if type(candidate_limit) is not int or not 1 <= candidate_limit <= 32:
            raise ValueError("Bounded candidate limit required")
        duration = (utc_instant(deadline_utc) - started).total_seconds()
        if duration <= 0:
            raise ValueError("Future original deadline required")
        stop = time.monotonic() + min(duration, 60)
        root, authority, ref, writer = _open_authority(authority_path, authority_sha)
        if datetime.now(UTC) >= utc_instant(deadline_utc) or time.monotonic() >= stop:
            raise JournalUnavailable("Original maintenance deadline exhausted", write_outcome="NOT_STARTED")
        rows, failure = [], False
        with _MaintenanceJournal(
            root / authority["journalPath"],
            writer,
            storage_version=authority["storageVersion"],
            stop=stop,
            deadline_utc=deadline_utc,
        ) as journal:
            journal._maintenance_deadline = stop
            with journal._transaction():
                journal._raw_authority(root, ref)
                runs = _pending_runs(journal, candidate_limit)
            for run_id in runs:
                before = journal.raw_obligations(run_id, datetime.now(UTC).isoformat())
                try:
                    with journal._write_admission():
                        journal._raw_authority(root, ref)
                        closed = journal.closed_run(run_id)
                        if closed is not None:
                            journal.collect_closed_run(run_id, datetime.now(UTC).isoformat())
                    result = journal.collect_raw_run(
                        run_id,
                        datetime.now(UTC).isoformat(),
                        private_root=root,
                        authority_ref=ref,
                        candidate_limit=candidate_limit,
                        work_deadline_utc=deadline_utc,
                    )
                    outcome = result["status"]
                except (JournalUnavailable, OSError):
                    outcome, failure = "REFUSED", True
                after = journal.raw_obligations(run_id, datetime.now(UTC).isoformat())
                rows.append(
                    {
                        "runIdSha256": hashlib.sha256(run_id.encode()).hexdigest(),
                        "status": outcome,
                        "before": [v["status"] for v in before],
                        "after": [v["status"] for v in after],
                    }
                )
                if time.monotonic() >= stop:
                    failure = True
                    break
            _raw_ref(root, ref)
            return {
                "schemaVersion": "alk-raw-maintenance-result.v1",
                "status": "PARTIAL" if failure else "COMPLETE",
                "authoritySha256": authority_sha,
                "journalIdentity": journal.journal_identity,
                "startedAt": started.isoformat(),
                "finishedAt": datetime.now(UTC).isoformat(),
                "outcomes": rows,
                "nextDueAt": _next_pending_due(journal),
                "failure": "retention-refused" if failure else None,
                "retentionDays": 30,
                "assurance": "PROCEDURAL_SAME_ACCOUNT",
            }
    except (ValueError, KeyError, TypeError, IndexError, OSError, sqlite3.Error, JournalUnavailable) as exc:
        raise LifecycleError(
            "retention-authority-refused", "Pinned maintenance authority is unavailable or invalid"
        ) from exc
