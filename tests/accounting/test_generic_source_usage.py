"""UNIT_ONLY generic declared accounting fixtures; no host or billing proof."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent_lifecycle.accounting.declared_source_route import (
    canonical_source_bytes,
    prepare_project_opening,
    project_binding,
)
from agent_lifecycle.accounting.generic_source_usage import advance_project_source
from agent_lifecycle.accounting.source_usage_context import load_frozen_source_policy, load_source_usage_context
from agent_lifecycle.accounting.usage_types import source_reference
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.declared_source_schemas import (
    DATA_LIMIT,
    OWNER_BINDINGS,
    PROJECT_CARRY,
    PROJECT_POLICY,
    PROJECT_WINDOW,
    SOURCE_USAGE_ROLES,
    validate_project_carry,
    validate_project_policy,
)
from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2
from tests.workflow.test_stage_binding_adoption import adopt, fixture, prepare


def write_data(root: Path, path: str, data: bytes | dict[str, Any]) -> dict[str, Any]:
    raw = data if isinstance(data, bytes) else canonical_source_bytes(data)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return source_reference(path, raw)


def carry_data(root: Path) -> dict[str, Any]:
    # Larger opaque source snapshots must survive preparation byte for byte.
    raw = b'{"original":"UNIT_ONLY"}\n' + b" " * 70_000
    ref = write_data(root, "input/raw/origin.raw", raw)
    digest = ref["sha256"]
    carry = {
        "schemaVersion": PROJECT_CARRY,
        "sourceScopeId": "unit-original-scope",
        "originalRunStartedAt": "2020-01-01T00:00:00Z",
        "originalRunDeadlineAt": "2099-01-01T00:00:00Z",
        "sourceRefs": [{**ref, "path": "raw/origin.raw", "originalPath": "/opaque/foreign/source"}],
        "declaredUnitRecords": [
            {
                "id": "original-carry",
                "role": None,
                "unit": "service-booking",
                "quantity": 73,
                "bookingKind": "CARRIED_FORWARD",
                "originRefDigest": digest,
            },
            {
                "id": "failed-prior-work",
                "role": "worker",
                "unit": "service-booking",
                "quantity": 4,
                "bookingKind": "DECLARED_BOOKING",
                "originRefDigest": digest,
            },
        ],
        "knownPartials": [{"metric": "observed-tool-count", "unit": "process", "value": 7, "sourceRefDigest": digest}],
        "unknownIntervals": [
            {
                "id": "inherited-unknown",
                "roles": list(SOURCE_USAGE_ROLES),
                "reason": "whole host metrics unavailable",
                "sourceRefDigest": digest,
                "status": "UNAVAILABLE",
            }
        ],
        "financialAssurance": "DECLARED_SOURCE_ONLY",
    }
    write_data(root, "input/carry.json", carry)
    return carry


def carry_at_size(carry: dict[str, Any], size: int) -> dict[str, Any]:
    value = copy.deepcopy(carry)
    base = value["unknownIntervals"][0]
    value["unknownIntervals"] = [{**base, "id": f"padding-{i}", "reason": "x"} for i in range(64)]
    remaining = size - len(canonical_bytes(value))
    if remaining < 0:
        raise ValueError("padding base too large")
    for interval in value["unknownIntervals"]:
        count = min(1000, remaining)
        interval["reason"] += "x" * count
        remaining -= count
    if remaining:
        raise ValueError("padding capacity insufficient")
    assert len(canonical_bytes(value)) == size
    return validate_project_carry(value)


def minimal_nonempty_carry_at_size(value: dict[str, Any], size: int) -> dict[str, Any]:
    carry = copy.deepcopy(value)
    carry["declaredUnitRecords"] = [{**carry["declaredUnitRecords"][0], "id": "u"}]
    carry["knownPartials"] = []
    carry["sourceScopeId"] = "u"
    carry["sourceRefs"][0]["originalPath"] = "u"
    original = carry["unknownIntervals"][0]
    carry["unknownIntervals"] = [{**original, "id": f"p{i}", "reason": "x"} for i in range(64)]
    remain = size - len(canonical_bytes(carry))
    for row in carry["unknownIntervals"]:
        count = min(remain, 1000)
        row["reason"] += "x" * count
        remain -= count
    assert remain == 0
    return validate_project_carry(carry)


class GenericFixture:
    def __init__(self, root: Path, *, probe_only: bool = False, git_backed: bool = False, two_tasks: bool = False):
        self.root = root
        self.revision = "source"
        if git_backed:
            from tests.workflow.limited_usage_fixture_support import install_git_seed

            self.revision = install_git_seed(root)
        self.state_path, self.strategy_path, self.profile, self.entry = fixture(root)
        self.carry = carry_data(root)
        owners = {
            "schemaVersion": OWNER_BINDINGS,
            "requiredRoles": list(SOURCE_USAGE_ROLES),
            "ownerBindings": [
                {"actorId": "worker", "role": "worker", "taskIds": ["WS-01", "WS-02"] if two_tasks else ["WS-01"]}
            ],
        }
        write_data(root, "input/owners.json", owners)
        opening = prepare_project_opening(
            root,
            carry_path="input/carry.json",
            owner_bindings_path="input/owners.json",
            opening_out="tasks/strategy/source-inputs",
            source_root="work/source",
        )
        self.policy = {
            "schemaVersion": PROJECT_POLICY,
            "mode": "SOURCE_AUTHORING_LIMITED",
            "adapterId": "codex",
            "adapterHost": "codex",
            "taskIds": ["WS-01", "WS-02"] if two_tasks else ["WS-01"],
            "allowedModelClasses": ["standard-code", "strong-reasoning"],
            "accountingKind": "PROJECT_DECLARED_SOURCE",
            "openingRef": opening["openingRef"],
            "sourceAuthoringRegistryRef": opening["sourceAuthoringRegistryRef"],
            "financialSource": opening["financialSource"],
            "actualCapConformance": "UNAVAILABLE",
            "financialClosureAllowed": False,
        }
        self.manifest_path = root / "tasks/strategy/plan.manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text())
        self.manifest["runtimePolicy"] = {"sourceUsageCompletion": self.policy}
        self.manifest["baseRevision"] = {"sha": self.revision}
        self.manifest["workstreams"][0]["executionPolicy"] = {"availabilityProbeOnly": probe_only}
        self.manifest["planFiles"] = sorted(
            [
                "tasks/strategy/plan.manifest.json",
                *[
                    p.relative_to(root).as_posix()
                    for p in (root / "tasks/strategy/source-inputs").rglob("*")
                    if p.is_file()
                ],
            ]
        )
        if two_tasks:
            second = copy.deepcopy(self.manifest["workstreams"][0])
            second.update(id="WS-02", dependsOn=["WS-01"], executionPolicy={"availabilityProbeOnly": False})
            self.manifest["workstreams"].append(second)
        self.refreeze()

    def refreeze(self) -> None:
        write_data(self.root, "tasks/strategy/plan.manifest.json", self.manifest)
        lock = build_plan_lock_v2(self.manifest, repository_root=self.root)
        write_data(self.root, "tasks/strategy/plan.lock.json", lock)
        state = json.loads(self.state_path.read_text())
        state["planDigest"] = canonical_digest(self.manifest)
        state["sourceRevision"] = self.revision
        state["runStartedAt"] = "2020-01-01T00:00:00Z"
        state["runDeadlineAt"] = "2099-01-01T00:00:00Z"
        write_data(self.root, self.state_path.name, state)

    def start(self) -> None:
        prepare(self.root, self.state_path, self.strategy_path, self.profile, source_revision=self.revision)
        adopt(self.state_path, self.strategy_path, source_revision=self.revision)

    def context(self) -> Any:
        state = json.loads(self.state_path.read_text())
        return load_frozen_source_policy(self.root, state, state["tasks"][0])

    def window(self, name: str = "original") -> dict[str, Any]:
        context = self.context()
        state = json.loads(self.state_path.read_text())
        current = context.source.read_current()
        return {
            "schemaVersion": PROJECT_WINDOW,
            "id": name,
            "sequence": current["head"]["sequence"] + 1,
            "openingSha256": self.policy["openingRef"]["sha256"],
            "previousHeadSha256": current["headSha256"],
            "binding": project_binding(context.inputs, state, state["tasks"][0], name),
            "declaredTokenHold": 9000,
            "sourceContextRefs": [],
            "observations": [],
            "costStatus": "UNAVAILABLE",
            "actualTokens": None,
            "actualUSD": None,
            "financialClosure": "OPEN_UNAVAILABLE",
        }


class GenericSourceUsageTests(unittest.TestCase):
    def test_opening_carry_opaque_blobs_and_full_hold_ancestry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = GenericFixture(Path(tmp))
            self.assertEqual(
                (f.root / "input/raw/origin.raw").read_bytes(),
                (f.root / "tasks/strategy/source-inputs/raw/origin.raw").read_bytes(),
            )
            f.start()
            context = f.context()
            window = f.window()
            before = context.source.read_current()
            after = advance_project_source(context.inputs, window, before["headSha256"])
            projection = context.source.project(after)
            self.assertEqual(projection["declaredUnitRecords"], f.carry["declaredUnitRecords"])
            self.assertEqual(projection["knownPartials"], f.carry["knownPartials"])
            self.assertEqual(projection["unknownIntervals"], f.carry["unknownIntervals"])
            self.assertEqual(len(after["ancestryHeadSha256s"]), 2)
            self.assertIsNone(projection["balances"]["actualTokens"])
            self.assertEqual(
                advance_project_source(context.inputs, window, before["headSha256"])["headRaw"], after["headRaw"]
            )
            duplicate = f.window("other-id")
            with self.assertRaises(LifecycleError):
                advance_project_source(context.inputs, duplicate, after["headSha256"])

    def test_pending_crash_stale_cas_and_foreign_history_refuse(self) -> None:
        for failure in ("stale", "crash", "ancestor"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                f = GenericFixture(Path(tmp))
                f.start()
                context, window = f.context(), f.window()
                before = context.source.read_current()
                if failure == "stale":
                    with self.assertRaises(LifecycleError):
                        advance_project_source(context.inputs, window, "0" * 64)
                    self.assertEqual(context.source.read_current()["headRaw"], before["headRaw"])
                elif failure == "crash":
                    with (
                        patch(
                            "agent_lifecycle.accounting.declared_ledger.replace_authority_bytes",
                            side_effect=OSError("UNIT crash"),
                        ),
                        self.assertRaises(OSError),
                    ):
                        advance_project_source(context.inputs, window, before["headSha256"])
                    self.assertTrue((f.root / "work/source/HEAD.pending.json").exists())
                    with self.assertRaises(LifecycleError):
                        context.source.read_current()
                else:
                    advance_project_source(context.inputs, window, before["headSha256"])
                    history = next((f.root / "work/source/declared-source-head-history").glob("*.json"))
                    history.write_bytes(b"{}")
                    with self.assertRaises(LifecycleError):
                        context.source.read_current()

    def test_missing_foreign_seed_prefix_owner_mutable_lock_and_context_refuse(self) -> None:
        for mutation in ("seed", "prefix", "owner", "mutable-lock", "selector", "source"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                f = GenericFixture(Path(tmp))
                if mutation == "seed":
                    (f.root / f.policy["financialSource"]["seedRef"]["path"]).write_bytes(b"{}")
                elif mutation == "prefix":
                    (f.root / f.policy["sourceAuthoringRegistryRef"]["path"]).write_bytes(b"{}")
                elif mutation == "owner":
                    f.manifest["workstreams"][0]["owner"] = "foreign"
                    f.refreeze()
                elif mutation == "mutable-lock":
                    f.manifest["planFiles"].append("work/source/HEAD.json")
                    f.manifest["planFiles"].sort()
                    with self.assertRaises(LifecycleError):
                        f.refreeze()
                    continue
                elif mutation == "selector":
                    f.policy["financialSource"]["route"] = "foreign"
                    f.refreeze()
                else:
                    (f.root / "tasks/strategy/source-inputs/raw/origin.raw").write_bytes(b"truncated")
                with self.assertRaises(LifecycleError):
                    f.context()

    def test_risk_context_remains_source_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = GenericFixture(Path(tmp))
            state = json.loads(f.state_path.read_text())
            context = load_source_usage_context(f.root, f.manifest, state, state["tasks"][0], "codex", "codex")
            assert context is not None
            self.assertEqual(context.policyDigest, canonical_digest(f.policy))
            self.assertTrue(context.appliesToTask)

    def test_accepted_source_binding_preserves_route_and_refuses_active_fallback(self) -> None:
        """Accepted history uses the durable route; active state never falls back."""
        with tempfile.TemporaryDirectory() as directory:
            f = GenericFixture(Path(directory).resolve())
            f.start()
            context = f.context()
            state = json.loads(f.state_path.read_text())
            active = state["tasks"][0]
            expected = project_binding(context.inputs, state, active, "regression-window")
            accepted = copy.deepcopy(active)
            accepted["status"] = "ACCEPTED"
            accepted.pop("attemptModelRoute")
            self.assertEqual(project_binding(context.inputs, state, accepted, "regression-window"), expected)
            for status in ("PENDING", "RUNNING", "VERIFYING"):
                with self.subTest(status=status), self.assertRaises(LifecycleError):
                    project_binding(context.inputs, state, {**accepted, "status": status}, "regression-window")
            incoherent = {**accepted, "attemptModelRoute": active["attemptModelRoute"]}
            with self.assertRaises(LifecycleError):
                project_binding(context.inputs, state, incoherent, "regression-window")

    def test_duplicate_window_identity_and_valid_canonical_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            f = GenericFixture(root)
            f.start()
            context = f.context()
            first = f.window("first")
            initial = context.source.read_current()
            one = advance_project_source(context.inputs, first, initial["headSha256"])
            second = f.window("second")
            second["binding"]["semanticOperationId"] = "unit-distinct-operation"
            two = advance_project_source(context.inputs, second, one["headSha256"])
            self.assertEqual([p["windowId"] for p in context.source.project(two)["windowPools"]], ["first", "second"])
            altered = copy.deepcopy(second)
            altered["id"] = "first"
            altered["binding"]["originalWindowId"] = "first"
            changed_ref = write_data(root, "work/source/windows/second.json", altered)
            head = copy.deepcopy(two["head"])
            head["windows"][-1] = {**changed_ref, "path": "windows/second.json"}
            write_data(root, "work/source/HEAD.json", head)
            observation = {"case": "duplicate-id-distinct-path", "expected": "REFUSED", "validCanonicalPositive": True}
            try:
                current = context.source.read_current()
                pools = context.source.project(current)["windowPools"]
            except LifecycleError as exc:
                observation.update(actual="REFUSED", code=exc.code)
            else:
                observation.update(
                    actual="ACCEPTED",
                    windowIds=[p["windowId"] for p in pools],
                    eligibility=[p["eligibility"] for p in pools],
                )
            self.assertIn(
                observation["actual"], {"REFUSED", "ACCEPTED", "REFUSED_BEFORE_WRITES", "REFUSED_AFTER_WRITES"}
            )
            self.assertEqual(
                observation["actual"], "REFUSED", "ACCOUNTING-01: duplicate original window IDs exposed as eligible"
            )

    def test_opening_final_serialized_byte_boundary(self) -> None:
        for size in (DATA_LIMIT - 1, DATA_LIMIT):
            with self.subTest(canonicalPayloadBytes=size), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                f = GenericFixture(root)
                carry = carry_at_size(f.carry, size)
                write_data(root, "input/boundary-carry.json", canonical_bytes(carry))
                observation: dict[str, Any] = {
                    "case": "opening-final-byte-bound",
                    "canonicalPayloadBytes": size,
                    "expected": "ACCEPTED" if size == DATA_LIMIT - 1 else "REFUSED_BEFORE_WRITES",
                }
                try:
                    opening = prepare_project_opening(
                        root,
                        carry_path="input/boundary-carry.json",
                        owner_bindings_path="input/owners.json",
                        opening_out="boundary-inputs",
                        source_root="boundary-source",
                    )
                except LifecycleError as exc:
                    observation.update(actual="REFUSED_BEFORE_WRITES", code=exc.code)
                    self.assertFalse((root / "boundary-inputs").exists())
                    self.assertFalse((root / "boundary-source").exists())
                else:
                    seed = opening["financialSource"]["seedRef"]
                    observation.update(
                        actual="ACCEPTED",
                        serializedCarryBytes=seed["bytes"],
                        outputFiles=len(
                            [
                                p
                                for d in (root / "boundary-inputs", root / "boundary-source")
                                for p in d.rglob("*")
                                if p.is_file()
                            ]
                        ),
                    )
                    policy = {
                        **f.policy,
                        "openingRef": opening["openingRef"],
                        "sourceAuthoringRegistryRef": opening["sourceAuthoringRegistryRef"],
                        "financialSource": opening["financialSource"],
                    }
                    try:
                        validate_project_policy(policy)
                    except LifecycleError as exc:
                        observation["consumerPolicy"] = {"status": "REFUSED", "code": exc.code}
                    else:
                        observation["consumerPolicy"] = {"status": "ACCEPTED"}
                    if size == DATA_LIMIT - 1:
                        self.assertEqual(seed["bytes"], DATA_LIMIT)
                        self.assertEqual(observation["consumerPolicy"]["status"], "ACCEPTED")
                self.assertIn(
                    observation["actual"], {"REFUSED", "ACCEPTED", "REFUSED_BEFORE_WRITES", "REFUSED_AFTER_WRITES"}
                )
                self.assertEqual(
                    observation["actual"],
                    observation["expected"],
                    "ACCOUNTING-02: serialization newline exceeds consumer bound after writes",
                )

    def test_window_serialized_byte_boundary(self) -> None:
        from agent_lifecycle.contracts.declared_source_schemas import validate_project_window

        for size in (DATA_LIMIT - 1, DATA_LIMIT):
            with self.subTest(canonicalPayloadBytes=size), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                f = GenericFixture(root)
                f.start()
                context = f.context()
                value = f.window("boundary")
                value["sourceContextRefs"] = [
                    {"path": f"context/{i}/data.raw", "sha256": hashlib.sha256(b"x").hexdigest(), "bytes": 1}
                    for i in range(96)
                ]
                remaining = size - len(canonical_bytes(value))
                for row in value["sourceContextRefs"]:
                    extra = min(700, remaining)
                    blocks, tail = divmod(extra, 101)
                    row["path"] = row["path"].replace("data.raw", ("x" * 100 + "/") * blocks + "y" * tail + "data.raw")
                    remaining -= extra
                    target = root / row["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"x")
                self.assertEqual(remaining, 0)
                self.assertEqual(len(canonical_bytes(value)), size)
                validate_project_window(value)
                current = context.source.read_current()
                initial_files = sorted(
                    p.relative_to(root).as_posix() for p in (root / "work/source").rglob("*") if p.is_file()
                )
                observation: dict[str, Any]
                try:
                    advanced = advance_project_source(context.inputs, value, current["headSha256"])
                except LifecycleError as exc:
                    files = sorted(
                        p.relative_to(root).as_posix() for p in (root / "work/source").rglob("*") if p.is_file()
                    )
                    actual = "REFUSED_BEFORE_WRITES" if files == initial_files else "REFUSED_AFTER_WRITES"
                    observation = {
                        "case": "actual-window-final-byte-bound",
                        "canonicalPayloadBytes": size,
                        "actual": actual,
                        "code": exc.code,
                        "newSourceFiles": sorted(set(files) - set(initial_files)),
                    }
                else:
                    observation = {
                        "case": "actual-window-final-byte-bound",
                        "canonicalPayloadBytes": size,
                        "actual": "ACCEPTED",
                        "serializedWindowBytes": advanced["head"]["windows"][-1]["bytes"],
                    }
                self.assertIn(
                    observation["actual"], {"REFUSED", "ACCEPTED", "REFUSED_BEFORE_WRITES", "REFUSED_AFTER_WRITES"}
                )
                self.assertEqual(
                    observation["actual"], "ACCEPTED" if size == DATA_LIMIT - 1 else "REFUSED_BEFORE_WRITES"
                )
