"""Pure source-qualified normalization; candidates grant no dispatch authority."""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import asdict
from typing import TYPE_CHECKING, TypedDict, cast

from .contracts import (
    AuthoritativeReceipt,
    BudgetPolicy,
    BudgetScope,
    CoverageAtom,
    EvidenceRef,
    ImportAmendment,
    Operation,
    SourceProfile,
    UsageObservation,
    UsageOutcome,
    _JournalStoragePort,
    canonical,
    digest,
    uint,
)
from .workflow_store import _apply, _BindingConflict, _operation, _projection, _refresh_v2

if TYPE_CHECKING:

    class _CounterSlice(TypedDict):
        atom: dict
        start: int
        end: int


class UsageUnavailable(ValueError):
    """The input is insufficient for a qualified accounting effect."""

    def __init__(self, message: str, *, kind: str = "SOURCE_OBSERVATION") -> None:
        super().__init__(message)
        self.kind = kind


class UsageConflict(ValueError):
    """A complete observation contradicts an immutable binding."""


def atom_semantics(atom: CoverageAtom, profile: SourceProfile) -> dict:
    value = asdict(atom)
    value.pop("membership_proof")
    value["role"] = dict(profile.role_mapping).get(atom.role, atom.role)
    return value


def coverage_digest(atoms: tuple[CoverageAtom, ...]) -> str:
    return digest(sorted((asdict(a) for a in atoms), key=canonical))


def semantic_final(
    operation: Operation, receipt: AuthoritativeReceipt, atoms: tuple[CoverageAtom, ...], profile: SourceProfile
) -> dict:
    """Validate equivalence facts; proof/receipt IDs are not semantic identity."""
    operation.__post_init__()
    receipt.__post_init__()
    profile.__post_init__()
    binding = asdict(operation)
    if (
        profile.budget_scope_id != operation.budget_scope_id
        or profile.source_id != operation.source_id
        or profile.unit_definition_id != operation.unit_definition_id
    ):
        raise UsageConflict("Profile does not qualify original operation domain")
    for name in (
        "budget_scope_id",
        "operation_id",
        "dispatch_key",
        "permit_id",
        "attempt_id",
        "route_id",
        "source_id",
        "unit_definition_id",
    ):
        if getattr(receipt, name) != binding[name]:
            raise UsageConflict("Final operation binding mismatch")
    if receipt.binding_digest != operation.binding_digest:
        raise UsageConflict("Final operation digest mismatch")
    if receipt.source_schema_version != profile.schema_version or receipt.attestation != profile.qualification_ref:
        raise UsageUnavailable("Finality/authority not qualified by pinned profile")
    if not atoms:
        raise UsageUnavailable("Complete atom partition required, including authoritative zero")
    if len({a.key for a in atoms}) != len(atoms):
        raise UsageConflict("Duplicate atoms in final partition")
    for a in atoms:
        a.__post_init__()
        role = dict(profile.role_mapping).get(a.role, a.role)
        if (
            a.namespace != profile.coverage_namespace
            or a.operation_id != operation.operation_id
            or a.operation_digest != operation.binding_digest
            or a.task_id != operation.task_id
            or role != operation.role
        ):
            raise UsageConflict("Atom attribution mismatch")
        if a.amount is None:
            raise UsageUnavailable("Unknown atom amount")
    if sum(cast(int, a.amount) for a in atoms) != receipt.reported_tokens:
        raise UsageConflict("Final amount differs from complete atom partition")
    if receipt.coverage.digest != coverage_digest(atoms):
        raise UsageConflict("Final coverage proof binding mismatch")
    return {
        "operation": binding,
        "amount": receipt.reported_tokens,
        "unit": receipt.unit_definition_id,
        "atoms": sorted((atom_semantics(a, profile) for a in atoms), key=canonical),
    }


def component_total(profile: SourceProfile, observation: UsageObservation) -> int:
    parts = observation.components
    total = observation.total
    if parts:
        if parts.get("input") is None or parts.get("output") is None:
            raise UsageUnavailable("Incomplete input/output components")
        computed = cast(int, parts["input"]) + cast(int, parts["output"])
        for name, subset, parent in (
            ("cached", profile.cached_is_subset, "input"),
            ("reasoning", profile.reasoning_is_subset, "output"),
        ):
            if name in parts:
                if parts[name] is None:
                    raise UsageUnavailable("Unknown component")
                if subset and cast(int, parts[name]) > cast(int, parts[parent]):
                    raise UsageConflict("Subset exceeds parent component")
                if not subset:
                    computed += cast(int, parts[name])
            elif not subset:
                raise UsageUnavailable("Required disjoint component absent")
        if total is not None and computed != total:
            raise UsageConflict("Declared total disagrees with qualified component semantics")
        total = computed
    if total is None:
        raise UsageUnavailable("Missing usage is not zero")
    return total


def counter_interval(
    profile: SourceProfile, observation: UsageObservation, baseline: dict | None, total: int, amount: int
) -> tuple[dict | None, bool]:
    """Advance a proved frontier or corroborate an exact previously covered interval."""
    if baseline is None or baseline["epoch"] != observation.epoch:
        raise UsageUnavailable("Proven counter origin/cutoff required", kind="SOURCE_BOUNDARY")
    members = {canonical(m.key): m for m in observation.interval_memberships}
    atoms = {canonical(a.key): a for a in observation.atoms}
    if len(members) != len(observation.interval_memberships):
        raise UsageConflict("Repeated counter membership")
    if set(members) != set(atoms):
        raise UsageUnavailable("Exact qualified counter membership required", kind="SOURCE_BOUNDARY")
    frontier = baseline.get("frontier")
    if frontier is None:
        raise UsageUnavailable("Counter frontier requires explicit provenance", kind="SOURCE_BOUNDARY")
    incoming: dict[str, _CounterSlice] = {
        key: {"atom": atom_semantics(atoms[key], profile), "start": m.start_sequence, "end": m.end_sequence}
        for key, m in members.items()
    }
    covered = frontier["members"]
    if observation.sequence > baseline["sequence"]:
        if total < baseline["total"] or total - baseline["total"] != amount:
            raise UsageUnavailable("Counter reset or unproved cumulative interval", kind="SOURCE_BOUNDARY")
        for key, value in incoming.items():
            if key in covered or key in frontier["precutoff_atoms"]:
                raise UsageConflict("Paid unit already covered by this counter frontier")
            if not (baseline["sequence"] <= value["start"] < value["end"] <= observation.sequence):
                raise UsageUnavailable("Counter membership lies outside new interval", kind="SOURCE_BOUNDARY")
        after = copy.deepcopy(baseline)
        after.update(sequence=observation.sequence, total=total)
        after["checkpoints"][str(observation.sequence)] = total
        after["frontier"]["members"].update(incoming)
        return after, False
    # A late point may be new, but its ordered partition must already be proved.
    # Start may precede the nearest checkpoint (a repeated aggregate interval).
    start = min(m.start_sequence for m in members.values())
    origin_total = baseline["checkpoints"].get(str(start))
    cutoff_total = baseline["checkpoints"].get(str(frontier["origin_sequence"]))
    if cutoff_total is None or start < frontier["origin_sequence"]:
        raise UsageUnavailable("Late interval origin is unproved", kind="SOURCE_BOUNDARY")
    expected, prefix_amount = {}, 0
    for key, value in covered.items():
        if value["start"] < start < value["end"] or value["start"] < observation.sequence < value["end"]:
            raise UsageUnavailable("Late point splits an indivisible counter membership", kind="SOURCE_BOUNDARY")
        if value["end"] <= start:
            prefix_amount += value["atom"]["amount"]
        if start <= value["start"] and value["end"] <= observation.sequence:
            expected[key] = value
    if origin_total is None:
        # The frontier is complete from its cutoff through the accepted endpoint.
        # Ordered members prove this boundary even if it never arrived as a point.
        origin_total = cutoff_total + prefix_amount
    if incoming != expected:
        raise UsageUnavailable("Late counter partition differs from proved frontier", kind="SOURCE_BOUNDARY")
    if total != origin_total + sum(v["atom"]["amount"] for v in expected.values()):
        raise UsageUnavailable("Late counter amount differs from proved interval", kind="SOURCE_BOUNDARY")
    prior = baseline["checkpoints"].get(str(observation.sequence))
    if prior is not None:
        if prior != total:
            raise UsageConflict("Counter checkpoint changed")
        return None, True
    after = copy.deepcopy(baseline)
    after["checkpoints"][str(observation.sequence)] = total
    return after, True


def normalize(profile: SourceProfile, observation: UsageObservation, snapshot: dict) -> dict:
    """snapshot contains current stored operations and a pinned baseline, if any."""
    profile.__post_init__()
    observation.__post_init__()
    if observation.profile_id != profile.profile_id:
        raise UsageConflict("Profile identity mismatch")
    if observation.kind == "STREAM":
        raise UsageUnavailable("Streaming usage is observation-only")
    total = component_total(profile, observation)
    if not observation.atoms or any(a.amount is None for a in observation.atoms):
        raise UsageUnavailable("Complete paid-unit partition required")
    if len({a.key for a in observation.atoms}) != len(observation.atoms):
        raise UsageConflict("Duplicate atom identity")
    if any(a.epoch != observation.epoch for a in observation.atoms):
        raise UsageConflict("Atom epoch mismatch")
    amount = sum(cast(int, a.amount) for a in observation.atoms)
    baseline = snapshot.get("baseline")
    advance = None
    if profile.counter_mode == "CUMULATIVE":
        advance, late = counter_interval(profile, observation, baseline, total, amount)
    else:
        if total != amount:
            raise UsageConflict("Parent/final total differs from complete partition")
        late = False
    groups: dict[str, list[CoverageAtom]] = {}
    for atom in observation.atoms:
        groups.setdefault(atom.operation_id, []).append(atom)
    finals = {v.operation_id: v for v in observation.receipts}
    if len(finals) != len(observation.receipts):
        raise UsageConflict("Multiple finals for the same operation")
    if observation.kind == "PARENT":
        if observation.receipts:
            raise UsageConflict("Parent finals must be derived from the qualified partition")
        for operation_id, atoms in groups.items():
            op = snapshot["operations"].get(operation_id)
            if op is None:
                raise UsageUnavailable("Parent lacks original operation binding")
            atom_tuple = tuple(atoms)
            event = "derived:" + digest(
                [profile.source_id, observation.source_event_id, operation_id, coverage_digest(atom_tuple)]
            )
            finals[operation_id] = AuthoritativeReceipt(
                receipt_id=event,
                budget_scope_id=op.budget_scope_id,
                operation_id=operation_id,
                dispatch_key=op.dispatch_key,
                permit_id=op.permit_id,
                binding_digest=op.binding_digest,
                attempt_id=op.attempt_id,
                route_id=op.route_id,
                source_id=op.source_id,
                source_event_id=event,
                source_schema_version=profile.schema_version,
                unit_definition_id=op.unit_definition_id,
                reported_tokens=sum(cast(int, a.amount) for a in atoms),
                coverage=EvidenceRef("derived:partition", coverage_digest(atom_tuple)),
                raw_evidence=observation.raw_evidence,
                attestation=profile.qualification_ref,
            )
    if set(finals) != set(groups):
        raise UsageUnavailable("Every operation needs a qualified final")
    results = []
    for operation_id, atoms in groups.items():
        op = snapshot["operations"].get(operation_id)
        if op is None:
            raise UsageUnavailable("Unknown original operation")
        receipt = finals[operation_id]
        if receipt.raw_evidence != observation.raw_evidence:
            raise UsageConflict("Final raw proof differs from observation")
        semantics = semantic_final(op, receipt, tuple(atoms), profile)
        results.append({"receipt": asdict(receipt), "semantics": semantics, "atoms": [asdict(a) for a in atoms]})
    if observation.kind == "FINAL" and (
        len(finals) != 1 or next(iter(finals.values())).source_event_id != observation.source_event_id
    ):
        raise UsageConflict("Leaf raw event and final event must have one immutable binding")
    return {
        "finals": results,
        "baseline": advance,
        "late": late,
        "amount": amount,
        "profile_digest": profile.profile_digest,
    }


def _validate_import_identity(scope: str, original: dict, completed: dict) -> None:
    for field in ("opening_balance_id", "source_id", "unit_definition_id", "cutoff", "proof", "covered_source_events"):
        if original["opening"][field] != completed["opening"][field]:
            raise _BindingConflict("Opening identity/cutoff changed", (scope,))
    for key, amount in {**original["opening"]["task_spent"], "": original["opening"]["run_overhead"]}.items():
        replacement = completed["opening"]["run_overhead"] if key == "" else completed["opening"]["task_spent"][key]
        if amount is not None and amount != replacement:
            raise _BindingConflict("Accepted opening balance changed", (scope,))
    for field in ("historical", "profiles", "baselines"):
        if any(item not in completed[field] for item in original[field]):
            raise _BindingConflict("Original import facts replaced", (scope,))
    if original["pending"] is not None and completed["pending"] != original["pending"]:
        raise _BindingConflict("Original pending inventory changed", (scope,))


class JournalNormalizationMixin(_JournalStoragePort):
    def register_source_profile(self, scope: str, profile: SourceProfile) -> UsageOutcome:
        profile.__post_init__()
        with self._transaction():
            closed = self._closed_scope(scope)
            if closed:
                return UsageOutcome("CLOSED", closed["revision"])
            state, revision = self._load(scope)
            if state is None or state.get("mode") != "COVERAGE_V2":
                return UsageOutcome("UNAVAILABLE", revision, "Qualified opening import required")
            if profile.budget_scope_id != scope or profile.unit_definition_id != state["scope"]["unit_definition_id"]:
                return UsageOutcome(self._conflict((scope,), "Profile domain mismatch", asdict(profile)), revision + 1)
            old = state["profiles"].get(profile.profile_id)
            if old is not None:
                if old != json.loads(canonical(asdict(profile))):
                    return UsageOutcome(self._conflict((scope,), "Profile pin changed", asdict(profile)), revision + 1)
                return UsageOutcome("ALREADY_REGISTERED", revision)
            if any(p["source_id"] == profile.source_id for p in state["profiles"].values()):
                return self._v2_unavailable(
                    scope,
                    state,
                    revision,
                    "A new profile identity for an existing source requires explicit reconciliation",
                    asdict(profile),
                )
            after = copy.deepcopy(state)
            after["profiles"][profile.profile_id] = asdict(profile)
            entry = self._entry(
                "source_profiles", [scope, profile.profile_id], scope, profile.profile_id, asdict(profile)
            )
            revision = self._commit_v2(
                scope, state, revision, "PROFILE_REGISTERED", after, [entry], [], asdict(profile)
            )
            return UsageOutcome("REGISTERED", revision)

    def ingest_usage(self, scope: str, observation: UsageObservation) -> UsageOutcome:
        observation.__post_init__()
        raw_data = json.loads(canonical(asdict(observation)))
        with self._transaction(scope):
            if self._closed_scope(scope):
                return UsageOutcome(
                    self._closed_evidence(scope, raw_data), cast(sqlite3.Row, self._closed_scope(scope))["revision"]
                )
            affected, problems = {scope}, []
            for candidate in self._observed_candidates(scope, raw_data):
                affected.update(self._binding_scopes(candidate))
                try:
                    self._check_observed(candidate)
                except _BindingConflict as exc:
                    affected.update(exc.scopes)
                    problems.append(str(exc))
            if problems:
                detail = "; ".join(sorted(set(problems)))
                self._conflict(tuple(sorted(affected)), detail, raw_data)
                return UsageOutcome("CONFLICT", self._load(scope)[1], detail)
            try:
                self._preflight_supplied_finals(scope, raw_data["receipts"])
            except _BindingConflict as exc:
                self._conflict(exc.scopes, str(exc), raw_data)
                return UsageOutcome("CONFLICT", self._load(scope)[1], str(exc))
            state, revision = self._load(scope)
            if state is None or state.get("mode") != "COVERAGE_V2":
                return UsageOutcome("UNAVAILABLE", revision, "Coverage-qualified scope required")
            data = state["profiles"].get(observation.profile_id)
            if data is None:
                return self._v2_unavailable(
                    scope, state, revision, "Source profile is unqualified", raw_data, reason_kind="SOURCE_PROFILE"
                )
            profile = SourceProfile(**{**data, "qualification_ref": EvidenceRef(**data["qualification_ref"])})
            raw_key = canonical([profile.source_id, observation.source_event_id])
            existing = self._db.execute("SELECT * FROM source_observations WHERE key=?", (raw_key,)).fetchone()
            if existing:
                old = json.loads(existing["payload"])
                if existing["scope"] != scope or old["observation_digest"] != digest(raw_data):
                    return UsageOutcome(
                        self._conflict((scope, existing["scope"]), "Raw observation identity changed", raw_data),
                        self._load(scope)[1],
                    )
            source_rows = self._db.execute(
                "SELECT * FROM identities WHERE kind IN ('source','observed_final') AND key=?", (raw_key,)
            ).fetchall()
            declared = {
                r.operation_id: digest(asdict(r))
                for r in observation.receipts
                if r.source_event_id == observation.source_event_id
            }
            for source_row in source_rows:
                if source_row["scope"] != scope or declared.get(source_row["owner"]) != source_row["digest"]:
                    return UsageOutcome(
                        self._conflict((scope, source_row["scope"]), "Raw/final source collision", raw_data),
                        self._load(scope)[1],
                    )
            try:
                baseline_key = canonical([profile.profile_id, observation.epoch])
                candidate = normalize(
                    profile,
                    observation,
                    {
                        "operations": {k: _operation(v["binding"]) for k, v in state["operations"].items()},
                        "baseline": state["baselines"].get(baseline_key),
                    },
                )
            except UsageUnavailable as exc:
                if observation.kind == "STREAM":
                    payload = {
                        "observation_digest": digest(raw_data),
                        "raw_digest": observation.raw_evidence.digest,
                        "finals": {},
                        "input": raw_data,
                    }
                    entry = self._entry(
                        "source_observations",
                        [profile.source_id, observation.source_event_id],
                        scope,
                        "observation",
                        payload,
                    )
                    if existing:
                        return UsageOutcome("OBSERVATION_RECORDED", revision)
                    # A stream cannot steal an already used final source identity.
                    keyrow = self._db.execute(
                        "SELECT * FROM identities WHERE kind='source' AND key=?", (raw_key,)
                    ).fetchone()
                    if keyrow:
                        return UsageOutcome(
                            self._conflict((scope, keyrow["scope"]), "Stream/source collision", raw_data),
                            self._load(scope)[1],
                        )
                    observed_keys = [
                        ["observed_final", [v["source_id"], v["source_event_id"]], scope, v["operation_id"], digest(v)]
                        for v in raw_data["receipts"]
                    ]
                    revision = self._commit_v2(
                        scope, state, revision, "OBSERVATION_RECORDED", state, [entry], observed_keys, raw_data
                    )
                    return UsageOutcome("OBSERVATION_RECORDED", revision)
                return self._v2_unavailable(scope, state, revision, str(exc), raw_data, reason_kind=exc.kind)
            except UsageConflict as exc:
                return UsageOutcome(self._conflict((scope,), str(exc), raw_data), self._load(scope)[1])
            return self._ingest_candidate(
                scope, observation, profile, state, revision, raw_data, candidate, existing, raw_key, baseline_key
            )

    def _ingest_candidate(
        self,
        scope: str,
        observation: UsageObservation,
        profile: SourceProfile,
        state: dict,
        revision: int,
        raw_data: dict,
        candidate: dict,
        existing: sqlite3.Row | None,
        raw_key: str,
        baseline_key: str,
    ) -> UsageOutcome:
        after = copy.deepcopy(state)
        entries, keys, outcomes = [], [], []
        raw_binding = {
            "observation_digest": digest(raw_data),
            "raw_digest": observation.raw_evidence.digest,
            "finals": {
                f["receipt"]["operation_id"]: digest(f["receipt"])
                for f in candidate["finals"]
                if f["receipt"]["source_event_id"] == observation.source_event_id
            },
            "input": raw_data,
        }
        entries.append(
            self._entry(
                "source_observations",
                [profile.source_id, observation.source_event_id],
                scope,
                "observation",
                raw_binding,
            )
        )
        entries.append(
            self._entry(
                "input_evidence",
                [scope, observation.raw_evidence.digest],
                scope,
                "raw",
                {"raw": observation.raw, "digest": observation.raw_evidence.digest},
            )
        )
        self._db.execute("SAVEPOINT v2_ingest")
        try:
            # Raw event and final keys share one collision domain even for
            # aggregate observations with no single final owner.
            row = self._db.execute("SELECT * FROM identities WHERE kind='source' AND key=?", (raw_key,)).fetchone()
            if row and (row["scope"] != scope or cast(dict, raw_binding["finals"]).get(row["owner"]) != row["digest"]):
                raise _BindingConflict("Raw/final source collision", (scope, row["scope"]))
            for final in candidate["finals"]:
                receipt = final["receipt"]
                owner = receipt["operation_id"]
                checksum = digest(receipt)
                self._source_preflight(receipt)
                op = after["operations"][owner]
                if not op["claim_id"] or op["state"] == "CANCELLED_WITH_NO_DISPATCH_PROOF":
                    raise _BindingConflict("Final contradicts original claim/cancellation", (scope,))
                first = after["accepted_finals"].get(owner)
                source_key = [receipt["source_id"], receipt["source_event_id"]]
                key = canonical(source_key)
                if first:
                    keys.append(["settlement", [scope, owner], scope, owner, digest(first["receipt"])])
                    if first["semantics"] != final["semantics"]:
                        raise _BindingConflict("Final semantic amount/binding/atoms changed", (scope,))
                    if digest(first["receipt"]) == checksum:
                        outcomes.append("ALREADY_SETTLED")
                    elif key in after["aliases"]:
                        if after["aliases"][key]["incoming_receipt_digest"] != checksum:
                            raise _BindingConflict("Corroborating alias changed", (scope,))
                        outcomes.append("ALREADY_CORROBORATED")
                    else:
                        alias = {
                            "original_owner": [scope, owner],
                            "accepted_u05_digest": digest(first["receipt"]),
                            "incoming_receipt_digest": checksum,
                            "raw_event_key": raw_key,
                            "raw_digest": observation.raw_evidence.digest,
                            "semantic_digest": digest(final["semantics"]),
                            "qualification_digest": profile.profile_digest,
                            "receipt": receipt,
                        }
                        after["aliases"][key] = alias
                        keys.append(["source", source_key, scope, owner, checksum])
                        entries.append(self._entry("corroborating_finals", source_key, scope, owner, alias))
                        outcomes.append("CORROBORATED")
                else:
                    if candidate["late"]:
                        raise UsageUnavailable("Late counter atoms have no accepted final owner")
                    uint(receipt["reported_tokens"])
                    uint(_projection(after, revision).known_spent + receipt["reported_tokens"])
                    keys.extend(
                        [
                            ["source", source_key, scope, owner, checksum],
                            ["settlement", [scope, owner], scope, owner, checksum],
                        ]
                    )
                    after = _apply(after, "SETTLE", {"operation_id": owner, "receipt": receipt})
                    after["accepted_finals"][owner] = {**final, "profile_id": profile.profile_id}
                    outcomes.append(
                        "SETTLED_BOUND_BROKEN"
                        if receipt["reported_tokens"] > op["binding"]["upper_bound_tokens"]
                        else "SETTLED"
                    )
                for atom in final["semantics"]["atoms"]:
                    entries.append(
                        self._entry(
                            "coverage_atoms",
                            [atom["namespace"], atom["epoch"], atom["atom_id"]],
                            scope,
                            owner,
                            atom,
                        )
                    )
            if candidate["baseline"] is not None:
                after["baselines"][baseline_key] = candidate["baseline"]
            if existing and all(x in {"ALREADY_SETTLED", "ALREADY_CORROBORATED"} for x in outcomes):
                self._db.execute("RELEASE v2_ingest")
                return UsageOutcome(
                    "ALREADY_CORROBORATED" if "ALREADY_CORROBORATED" in outcomes else "ALREADY_SETTLED", revision
                )
            kind = "NORMALIZED_BATCH" if any(x.startswith("SETTLED") for x in outcomes) else "FINAL_CORROBORATED"
            revision = self._commit_v2(scope, state, revision, kind, after, entries, keys, raw_data)
            self._db.execute("RELEASE v2_ingest")
            status = (
                "SETTLED_BOUND_BROKEN"
                if "SETTLED_BOUND_BROKEN" in outcomes
                else "SETTLED"
                if "SETTLED" in outcomes
                else "CORROBORATED"
                if "CORROBORATED" in outcomes
                else outcomes[0]
            )
            return UsageOutcome(status, revision)
        except (_BindingConflict, UsageUnavailable, ValueError) as exc:
            self._db.execute("ROLLBACK TO v2_ingest")
            self._db.execute("RELEASE v2_ingest")
            if isinstance(exc, _BindingConflict):
                return UsageOutcome(self._conflict(exc.scopes, str(exc), raw_data), self._load(scope)[1])
            return self._v2_unavailable(
                scope,
                state,
                revision,
                str(exc),
                raw_data,
                overflow=not isinstance(exc, UsageUnavailable),
                reason_kind=exc.kind if isinstance(exc, UsageUnavailable) else "OVERFLOW",
            )

    def reconcile_import(self, scope: str, amendment: ImportAmendment) -> UsageOutcome:
        if not isinstance(amendment.proof, EvidenceRef):
            raise ValueError("Evidence completion proof required")
        with self._transaction(scope):
            closed = self._closed_scope(scope)
            if closed:
                self._closed_evidence(scope, json.loads(canonical(asdict(amendment))))
                return UsageOutcome("CLOSED", closed["revision"])
            state, revision = self._load(scope)
            if (
                state is None
                or state.get("mode") != "COVERAGE_V2"
                or state.get("opening_import_digest") != amendment.opening_digest
            ):
                return UsageOutcome("UNAVAILABLE", revision, "Original opening lineage required")
            original = state["opening_import"]
            completed = json.loads(canonical(asdict(amendment.completed_import)))
            if completed == original:
                return UsageOutcome("ALREADY_RECONCILED", revision)
            policy = BudgetPolicy(
                **{**state["policy"], "authorization": EvidenceRef(**state["policy"]["authorization"])}
            )
            try:
                candidate = self._compile_opening(BudgetScope(**state["scope"]), policy, amendment.completed_import)
                # Completion cannot replace accepted opening facts or operations.
                _validate_import_identity(scope, original, completed)
                # Preserve all runtime operations and all their later charges; only
                # previously unknown opening subtotals can gain disjoint history.
                after = copy.deepcopy(state)
                additions = set(candidate["operations"]) - set(state["operations"])
                for owner in set(candidate["operations"]) & set(state["operations"]):
                    if candidate["operations"][owner]["binding"] != state["operations"][owner]["binding"]:
                        raise _BindingConflict("Original operation changed", (scope,))
                original_ids = {x["operation"]["operation_id"] for x in original["historical"]}
                original_ids.update(x["operation"]["operation_id"] for x in original["pending"] or [])
                if (set(candidate["operations"]) - original_ids) & set(state["operations"]):
                    raise _BindingConflict("New history overlaps runtime operations", (scope,))
                old_history = state.get("opening_history_known")
                if old_history is None:
                    raise UsageUnavailable("Untyped old opening history requires explicit migration")
                for key, amount in candidate["opening_history_known"].items():
                    if amount < old_history.get(key, 0):
                        raise _BindingConflict("Known historical lower bound reduced", (scope,))
                after["opening_history_known"] = dict(candidate["opening_history_known"])
                after["historical_operation_ids"] = list(candidate["historical_operation_ids"])
                for owner in additions:
                    after["operations"][owner] = candidate["operations"][owner]
                    if owner in candidate["accepted_finals"]:
                        after["accepted_finals"][owner] = candidate["accepted_finals"][owner]
                after["profiles"].update(candidate["profiles"])
                for key, baseline in candidate["baselines"].items():
                    current = after["baselines"].get(key)
                    if current is None:
                        after["baselines"][key] = baseline
                        continue
                    if "frontier" not in current:
                        raise UsageUnavailable("Untyped counter frontier requires explicit migration")
                    precutoff = set(baseline["frontier"]["precutoff_atoms"])
                    if precutoff & set(current["frontier"]["members"]):
                        raise _BindingConflict("Completed history overlaps post-cutoff counter interval", (scope,))
                    current["frontier"]["precutoff_atoms"] = sorted(
                        precutoff | set(current["frontier"]["precutoff_atoms"])
                    )
                # Remaining protection includes current effects, not just cutoff.
                after["protected"] = dict(policy.protected_closeout)
                for op in after["operations"].values():
                    binding = op["binding"]
                    if binding["operation_class"] == "CLOSEOUT":
                        consumed = (
                            min(binding["upper_bound_tokens"], op["actual"])
                            if op["actual"] is not None
                            else op["reservation"]
                        )
                        after["protected"][binding["closeout_allocation_id"]] -= consumed
                if any(v is None for v in candidate["protected"].values()):
                    after["protected"] = {key: None for key in after["protected"]}
                after["opening"]["pending_operations"] = candidate["opening"]["pending_operations"]
                after["opening_complete"] = candidate["opening_complete"]
                # Replace only opening incompleteness. Source/epoch/overflow and
                # operation reasons survive unless their own resolution is proved.
                remaining = {
                    key: value for key, value in after["unresolved_reasons"].items() if value["kind"] != "OPENING"
                }
                remaining.update(candidate["unresolved_reasons"])
                after["unresolved_reasons"] = remaining
                runtime = {key: 0 for key in candidate["opening_history_known"]}
                historical = set(after["historical_operation_ids"])
                for owner, op in after["operations"].items():
                    if owner not in historical and op["actual"] is not None:
                        runtime[op["binding"]["task_id"] or ""] += op["actual"]
                after["known_partials"] = {
                    key: amount + runtime[key] for key, amount in after["opening_history_known"].items()
                }
                for key, amount in candidate["task_spent"].items():
                    after["task_spent"][key] = None if amount is None else amount + runtime[key]
                after["overhead"] = None if candidate["overhead"] is None else candidate["overhead"] + runtime[""]
                try:
                    uint(sum(after["known_partials"].values()))
                except ValueError:
                    after["unresolved_reasons"]["amendment:overflow"] = {"kind": "OVERFLOW", "origin": "amendment"}
                    if after["gate"] not in {"CONFLICT", "CLOSED"}:
                        after["gate"] = "BOUND_BROKEN"
                if candidate["gate"] == "BOUND_BROKEN" and after["gate"] not in {"CONFLICT", "CLOSED"}:
                    after["gate"] = "BOUND_BROKEN"
                _refresh_v2(after)
                after["opening_import"] = completed
                # The original digest is the amendment lineage, never reset.
                self._db.execute("SAVEPOINT v2_amend")
                candidate["opening_import_digest"] = state["opening_import_digest"]
                entries, keys = self._import_entries(scope, candidate)
                keys = [k for k in keys if k[0] != "opening"]
                revision = self._commit_v2(
                    scope, state, revision, "IMPORT_EVIDENCE_COMPLETED", after, entries, keys, asdict(amendment)
                )
                self._db.execute("RELEASE v2_amend")
                return UsageOutcome("RECONCILED", revision)
            except (_BindingConflict, UsageUnavailable, UsageConflict) as exc:
                if self._db.execute("SELECT 1").fetchone():
                    try:
                        self._db.execute("ROLLBACK TO v2_amend")
                        self._db.execute("RELEASE v2_amend")
                    except sqlite3.OperationalError:
                        pass
                if isinstance(exc, UsageUnavailable):
                    return self._v2_unavailable(scope, state, revision, str(exc), asdict(amendment))
                return UsageOutcome(
                    self._conflict(getattr(exc, "scopes", (scope,)), str(exc), asdict(amendment)), self._load(scope)[1]
                )

    def _check_observed(self, candidate: dict) -> None:
        namespace, key = candidate["namespace"], candidate["key"]
        same = self._observed_lookup(namespace, key)
        if same and not self._binding_equal(same, candidate):
            raise _BindingConflict(
                "Immutable observed source identity collision",
                tuple(sorted(self._binding_scopes(same) | self._binding_scopes(candidate))),
            )
        other = self._observed_lookup("raw" if namespace == "final" else "final", key)
        if other is None:
            return
        raw, final = (other, candidate) if namespace == "final" else (candidate, other)
        matches = (
            not raw.get("ambiguous")
            and not final.get("ambiguous")
            and raw["scope"] == final["scope"]
            and raw.get("finals", {}).get(final["owner"]) == final["digest"]
            and (final.get("raw_digest") is None or raw["raw_digest"] == final["raw_digest"])
        )
        if not matches:
            raise _BindingConflict(
                "Raw/final source identity collision",
                tuple(sorted(self._binding_scopes(other) | self._binding_scopes(candidate))),
            )

    def _observed_candidates(self, scope: str, evidence: dict) -> list[dict]:
        result, receipts = [], []

        def visit(value):
            if isinstance(value, dict):
                if "receipt_id" in value and "source_id" in value and "source_event_id" in value:
                    receipts.append(value)
                else:
                    for child in value.values():
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(evidence)
        for receipt in receipts:
            result.append(
                {
                    "namespace": "final",
                    "key": canonical([receipt["source_id"], receipt["source_event_id"]]),
                    "scope": receipt["budget_scope_id"],
                    "owner": receipt["operation_id"],
                    "digest": digest(receipt),
                    "raw_digest": receipt["raw_evidence"]["digest"],
                }
            )
        if "profile_id" in evidence and "source_event_id" in evidence and "raw_evidence" in evidence:
            state, _ = self._load(scope)
            profile = (state or {}).get("profiles", {}).get(evidence["profile_id"])
            if profile:
                result.append(
                    {
                        "namespace": "raw",
                        "key": canonical([profile["source_id"], evidence["source_event_id"]]),
                        "scope": scope,
                        "owner": "observation",
                        "digest": digest(evidence),
                        "raw_digest": evidence["raw_evidence"]["digest"],
                        "finals": {
                            r["operation_id"]: digest(r)
                            for r in receipts
                            if r["source_event_id"] == evidence["source_event_id"]
                        },
                    }
                )
        return result
