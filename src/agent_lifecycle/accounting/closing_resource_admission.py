"""Closed-run admission and retained financial evidence for the journal."""
from __future__ import annotations
from .workflow_store import JournalUnavailable
from .workflow_store import RETENTION_TABLES
from .contracts import ROLES
from .workflow_store import RevisionConflict
from .workflow_store import _BindingConflict
from dataclasses import asdict
from .contracts import canonical
import copy
from .contracts import digest
from .contracts import identity
import json
from datetime import timedelta
from .contracts import uint
from .contracts import utc_instant
from .contracts import ClosureOutcome
from .contracts import RunClosure


class ClosureAdmissionMixin:
    @property
    def journal_identity(self) -> str:
        return self._db.execute("SELECT journal_id FROM retention_metadata WHERE singleton=1").fetchone()[0]
    def _retained(self, table: str, key: str) -> dict | None:
        if table not in RETENTION_TABLES:
            raise ValueError("Unknown retention table")
        row = self._db.execute(f"SELECT * FROM {table} WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row["payload"])
            if digest(value) != row["digest"] or canonical(value) != row["payload"]:
                raise ValueError("Retained digest mismatch")
            return value
        except (ValueError, TypeError, RecursionError) as exc:
            raise JournalUnavailable("Invalid retained financial record") from exc
    def _retain(self, table: str, key: str, scope: str, owner: str, payload: dict) -> None:
        old = self._retained(table, key)
        if old is not None:
            row = self._db.execute(f"SELECT scope,owner FROM {table} WHERE key=?", (key,)).fetchone()
            if canonical(old) != canonical(payload) or tuple(row) != (scope, owner):
                raise JournalUnavailable("Retained immutable binding conflict")
            return
        self._db.execute(
            f"INSERT INTO {table} VALUES(?,?,?,?,?)", (key, scope, owner, digest(payload), canonical(payload))
        )
    def _closed_scope(self, scope: str):
        return self._db.execute("SELECT * FROM closed_scopes WHERE scope=?", (scope,)).fetchone()
    def closed_run(self, run_id: str) -> dict | None:
        identity(run_id)
        value = self._retained("run_closures", run_id)
        if value is None:
            return None
        record = value["closure"]
        if record["run_id"] != run_id or digest(value["summary"]) != value["summary_digest"]:
            raise JournalUnavailable("Closed run binding mismatch")
        expected = {s: r + 1 for s, r in record["scope_revisions"]}
        actual = {r["scope"]: r for r in self._db.execute("SELECT * FROM closed_scopes WHERE run_id=?", (run_id,))}
        if set(actual) != set(expected) or any(
            actual[s]["revision"] != revision
            or actual[s]["closure_id"] != record["closure_id"]
            or actual[s]["summary_digest"] != value["summary_digest"]
            for s, revision in expected.items()
        ):
            raise JournalUnavailable("Closed scope registry mismatch")
        return value
    def close_run(self, closure: RunClosure, now_utc: str) -> ClosureOutcome:
        closure.__post_init__()
        now = utc_instant(now_utc)
        closed_at = utc_instant(closure.closed_at_utc)
        if closed_at > now:
            raise JournalUnavailable("Closure cannot precede final accounting or be in the future")
        data = json.loads(canonical(asdict(closure)))
        with self._transaction():
            prior = self.closed_run(closure.run_id)
            if prior is not None:
                if prior["closure"] != data:
                    raise JournalUnavailable("Run closure identity/content changed")
                return self._closure_outcome(prior, "ALREADY_CLOSED")
            inventory = {
                r["scope"]: r
                for r in self._db.execute("SELECT * FROM scope_state")
                if json.loads(r["data"])["scope"]["run_id"] == closure.run_id
            }
            if set(inventory) != {s for s, _ in closure.scope_revisions}:
                raise JournalUnavailable("Full-run scope inventory mismatch")
            summaries, states = {}, {}
            for scope, expected_revision in closure.scope_revisions:
                state, revision, _, _ = self._live_facts(scope)
                if revision != expected_revision or revision != inventory[scope]["revision"]:
                    raise RevisionConflict("Stale closure revision")
                if canonical(state) != canonical(json.loads(inventory[scope]["data"])):
                    raise JournalUnavailable("Closure projection differs from immutable replay")
                if state["scope"]["unit_definition_id"] != closure.unit_definition_id or self._closed_scope(scope):
                    raise JournalUnavailable("Closed scope unit/inventory mismatch")
                latest = self._db.execute(
                    "SELECT observed_at FROM events WHERE scope=? ORDER BY revision DESC LIMIT 1", (scope,)
                ).fetchone()[0]
                if utc_instant(latest) > closed_at:
                    raise JournalUnavailable("Closure precedes the last committed accounting observation")
                totals = self._financial_totals(state, revision)
                after = copy.deepcopy(state)
                after.update(gate="CLOSED", closure_id=closure.closure_id, original_gate=state["gate"])
                summaries[scope] = {
                    "revision": revision + 1,
                    "totals": totals,
                    "financial_digest": digest(self._financial_state(after)),
                }
                states[scope] = (state, revision, after)
            summary = {
                "scopes": summaries,
                "known_spent": sum(v["totals"]["known_spent"] for v in summaries.values()),
                "roles": {role: sum(v["totals"]["roles"][role] for v in summaries.values()) for role in ROLES},
            }
            uint(summary["known_spent"])
            value = {
                "closure": data,
                "summary": summary,
                "summary_digest": digest(summary),
                "eligible_after": (closed_at + timedelta(days=30)).isoformat(),
            }
            self._retain("run_closures", closure.run_id, closure.run_id, closure.closure_id, value)
            for scope, (state, revision, after) in states.items():
                self._db.execute(
                    "INSERT INTO closed_scopes VALUES(?,?,?,?,?)",
                    (scope, closure.run_id, closure.closure_id, revision + 1, value["summary_digest"]),
                )
                self._commit_v2(
                    scope,
                    state,
                    revision,
                    "RUN_CLOSED",
                    after,
                    [],
                    [],
                    {"closure_id": closure.closure_id, "summary_digest": value["summary_digest"]},
                )
            if self.fault_hook:
                self.fault_hook("after_run_closure")
            return self._closure_outcome(value, "CLOSED")
    @staticmethod
    def _binding_equal(left: dict, right: dict) -> bool:
        if left.get("ambiguous") or right.get("ambiguous"):
            return False
        fields = ("namespace", "key", "scope", "owner", "digest")
        if any(left.get(k) != right.get(k) for k in fields):
            return False
        return left["namespace"] != "raw" or all(left.get(k) == right.get(k) for k in ("raw_digest", "finals"))
    @staticmethod
    def _binding_scopes(binding: dict) -> set[str]:
        return {c["scope"] for c in binding["ambiguous"]} if binding.get("ambiguous") else {binding["scope"]}
    def _observed_lookup(self, namespace: str, key: str) -> dict | None:
        candidates = []
        if namespace == "final":
            for row in self._db.execute(
                "SELECT * FROM identities WHERE kind IN ('source','observed_final') AND key=?", (key,)
            ):
                candidates.append(
                    {
                        "namespace": namespace,
                        "key": key,
                        "scope": row["scope"],
                        "owner": row["owner"],
                        "digest": row["digest"],
                    }
                )
        else:
            row = self._db.execute("SELECT * FROM source_observations WHERE key=?", (key,)).fetchone()
            if row:
                value = json.loads(row["payload"])
                candidates.append(
                    {
                        "namespace": "raw",
                        "key": key,
                        "scope": row["scope"],
                        "owner": "observation",
                        "digest": value["observation_digest"],
                        "raw_digest": value["raw_digest"],
                        "finals": value.get("finals", {}),
                    }
                )
            archived = self._retained("archive_observation_keys", key)
            if archived:
                candidates.append(archived["binding"])
        extra = self._retained("exception_identity_keys", canonical([namespace, key]))
        if extra:
            record = self._retained("financial_exceptions", extra["exception_id"])
            if (
                record is None
                or extra["binding"] not in record["new_bindings"]
                or extra["declaration_digest"] != digest(extra["binding"])
            ):
                raise JournalUnavailable("Exception index has no original declaration")
            candidates.append(extra["binding"])
        # Missing projections are a recovery requirement, never evidence of a fresh key.
        declared = self._db.execute(
            "SELECT e.key FROM financial_exceptions e, json_each(e.payload,'$.new_bindings') b "
            "WHERE json_extract(b.value,'$.namespace')=? AND json_extract(b.value,'$.key')=? LIMIT 1",
            (namespace, key),
        ).fetchone()
        if declared and extra is None:
            raise JournalUnavailable("Missing exception identity projection; explicit rebuild required")
        if namespace == "raw" and not candidates:
            declared = self._db.execute(
                "SELECT a.key FROM archive_records a, json_each(a.payload,'$.protection.observations') o "
                "WHERE json_extract(o.value,'$.key')=? LIMIT 1",
                (key,),
            ).fetchone()
            if declared:
                raise JournalUnavailable("Missing archived observation projection; explicit rebuild required")
        if namespace == "final" and not candidates:
            for record in self._db.execute(
                "SELECT a.key,i.value FROM archive_records a, json_each(a.payload,'$.protection.identities') i "
                "WHERE json_extract(i.value,'$[0]') IN ('source','observed_final')"
            ):
                if canonical(json.loads(record[1])[1]) == key:
                    raise JournalUnavailable("Missing archived source projection; explicit rebuild required")
        if not candidates:
            return None
        first = candidates[0]
        for other in candidates[1:]:
            if canonical(first) != canonical(other) and not self._binding_equal(first, other):
                raise JournalUnavailable("Disagreeing global observation representations")
        return first
    def _exception_chain(self, run_id: str, *, restore: bool = False) -> list[dict]:
        records = [
            self._retained("financial_exceptions", r[0])
            for r in self._db.execute("SELECT key FROM financial_exceptions WHERE scope=?", (run_id,))
        ]
        records.sort(key=lambda r: r["ordinal"])
        previous, declarations = None, {}
        closure = self.closed_run(run_id)
        for ordinal, record in enumerate(records, 1):
            if (
                record["ordinal"] != ordinal
                or record["previous_digest"] != previous
                or record["closure_id"] != closure["closure"]["closure_id"]
            ):
                raise JournalUnavailable("Broken immutable financial exception chain")
            previous = digest(record)
            for binding in record["new_bindings"]:
                key = canonical([binding["namespace"], binding["key"]])
                if key in declarations:
                    raise JournalUnavailable("Financial exception redeclares an immutable owner")
                payload = {
                    "binding": binding,
                    "exception_id": record["exception_id"],
                    "declaration_digest": digest(binding),
                }
                declarations[key] = payload
                actual = self._retained("exception_identity_keys", key)
                if actual is None and restore:
                    self._retain("exception_identity_keys", key, run_id, record["exception_id"], payload)
                elif actual != payload:
                    raise JournalUnavailable("Financial exception identity projection mismatch")
        head = self._db.execute("SELECT ordinal,digest FROM exception_heads WHERE run_id=?", (run_id,)).fetchone()
        if (records and (head is None or tuple(head) != (len(records), previous))) or (
            not records and head is not None
        ):
            raise JournalUnavailable("Financial exception head mismatch")
        actual = {r[0] for r in self._db.execute("SELECT key FROM exception_identity_keys WHERE scope=?", (run_id,))}
        if actual != set(declarations):
            raise JournalUnavailable("Undeclared financial exception identity")
        return records
    def _append_exception(self, scope: str, evidence: dict, reason: str) -> str:
        closed = self._closed_scope(scope)
        if closed is None:
            raise JournalUnavailable("Closed owner required for financial exception")
        run_id = closed["run_id"]
        prior = self._exception_chain(run_id)
        event_id = digest([closed["closure_id"], scope, self._observation_scope or scope, digest(evidence)])
        saved = self._retained("financial_exceptions", event_id)
        if saved is not None:
            return event_id
        origin = self._observation_scope or scope
        candidates = self._observed_candidates(origin, evidence)
        groups, affected, declarations, claims = {}, {scope}, [], []
        for candidate in candidates:
            groups.setdefault((candidate["namespace"], candidate["key"]), {})[canonical(candidate)] = candidate
            affected.update(self._binding_scopes(candidate))
            try:
                self._check_observed(candidate)
            except _BindingConflict as exc:
                affected.update(exc.scopes)
            original = self._observed_lookup(candidate["namespace"], candidate["key"])
            claims.append({"candidate": candidate, "original": original})
        for (namespace, key), group in sorted(groups.items()):
            if self._observed_lookup(namespace, key) is not None:
                continue
            values = [group[k] for k in sorted(group)]
            binding = (
                values[0]
                if len(values) == 1
                else {"namespace": namespace, "key": key, "ambiguous": values, "digest": digest(values)}
            )
            declarations.append(binding)

        # Preserve amounts and lineage references without retaining raw body copies.
        def compact(value):
            if isinstance(value, dict):
                return {k: compact(v) for k, v in value.items() if k != "raw"}
            if isinstance(value, list):
                return [compact(v) for v in value]
            return value

        record = {
            "exception_id": event_id,
            "closure_id": closed["closure_id"],
            "scope": scope,
            "ordinal": len(prior) + 1,
            "previous_digest": digest(prior[-1]) if prior else None,
            "evidence_digest": digest(evidence),
            "evidence_scope": origin,
            "evidence": compact(evidence),
            "reason": reason,
            "claims": claims,
            "new_bindings": declarations,
            "qualification": "ACCOUNTING_RECONCILIATION_REQUIRED",
        }
        self._retain("financial_exceptions", event_id, run_id, scope, record)
        if self.fault_hook:
            self.fault_hook("after_financial_exception")
        for binding in declarations:
            key = canonical([binding["namespace"], binding["key"]])
            self._retain(
                "exception_identity_keys",
                key,
                run_id,
                event_id,
                {"binding": binding, "exception_id": event_id, "declaration_digest": digest(binding)},
            )
        self._db.execute(
            "INSERT INTO exception_heads VALUES(?,?,?) ON CONFLICT(run_id) "
            "DO UPDATE SET ordinal=excluded.ordinal,digest=excluded.digest",
            (run_id, record["ordinal"], digest(record)),
        )
        if self.fault_hook:
            self.fault_hook("after_exception_keys")
        for owner_scope in sorted(affected):
            if self._closed_scope(owner_scope):
                continue
            state, revision = self._load(owner_scope)
            if state is not None and state["gate"] != "CONFLICT":
                self._record(
                    owner_scope,
                    state,
                    revision,
                    "CONFLICT",
                    {"reason": "Closed-owner financial collision", "exception_id": event_id},
                )
        if self.fault_hook:
            self.fault_hook("after_exception_quarantine")
        return event_id
    def _closed_evidence(self, scope: str, evidence: dict) -> str:
        self._exception_chain(self._closed_scope(scope)["run_id"])
        state, _ = self._load(scope)
        candidates = self._observed_candidates(scope, evidence)
        conflicts = {scope}
        problems = []
        for candidate in candidates:
            conflicts.update(self._binding_scopes(candidate))
            try:
                self._check_observed(candidate)
            except _BindingConflict as exc:
                conflicts.update(exc.scopes)
                problems.append(str(exc))
        # An exact previous raw observation or first/alias final is a historical repeat.
        previous_exception = self._retained(
            "financial_exceptions",
            digest(
                [self._closed_scope(scope)["closure_id"], scope, self._observation_scope or scope, digest(evidence)]
            ),
        )
        if (
            not previous_exception
            and not problems
            and candidates
            and all(
                (old := self._observed_lookup(c["namespace"], c["key"])) is not None and self._binding_equal(old, c)
                for c in candidates
            )
        ):
            receipts = evidence.get("receipts", [evidence] if "receipt_id" in evidence else [])
            if receipts and all(
                state.get("accepted_finals", {}).get(r["operation_id"], {}).get("receipt") == r for r in receipts
            ):
                return "ALREADY_SETTLED"
            if receipts and all(
                canonical([r["source_id"], r["source_event_id"]]) in state.get("aliases", {}) for r in receipts
            ):
                return "ALREADY_CORROBORATED"
            if not receipts:
                return "OBSERVATION_RECORDED"
        self._append_exception(scope, evidence, "Post-closure financial evidence")
        for other in sorted(conflicts - {scope}):
            if self._closed_scope(other):
                self._append_exception(other, evidence, "Post-closure source identity collision")
        return "ACCOUNTING_RECONCILIATION_REQUIRED"
