"""Pure WR wire/signature joins: fixtures confer no host/operator authority."""

from copy import deepcopy
import hashlib
import unittest

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.closing_window_schemas import (
    ALLOWED_WRITES_V1, CLOSING_WINDOW_SCHEMAS, RUN_OUTPUT_ANCHOR_V1, WINDOW_REQUEST_V1,
    evaluate_window_request_data, load_window_request, validate_allowed_writes, validate_run_output_anchor,
    validate_window_intent, validate_window_request, window_intent,
)
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.workflow_authority_schemas import AUTHORITY_SNAPSHOT_V1
from tests.contracts.test_workflow_authority import _grant, _issuer, _pin, _signed

_SNAPSHOT_DOMAIN = b"agent-lifecycle-workflow-authority-snapshot-v1\x00"
_GRANT_DOMAIN = b"agent-lifecycle-workflow-closing-grant-v1\x00"
_OBSERVED = "2026-09-23T01:30:00.000000Z"
_CLASSES = ["CANONICAL_STATE_REPLACE", "EVENT_LOG_APPEND", "FINAL_PROOF_CREATE_ONCE",
            "PROOF_BODY_CREATE_ONCE"]


def _fixture() -> dict:
    grant = _grant()
    anchor = {
        "schemaVersion": RUN_OUTPUT_ANCHOR_V1, "bindingDigest": "a" * 64, "runId": "run",
        "adoptedStateDigest": "b" * 64, "journalIdentity": "journal", "storageProtocolVersion": "6",
        "artifactAuthorityRootPath": "/trusted", "artifactAuthorityRootIdentity": {
            "platform": "POSIX", "volumeId": "volume", "fileId": "root-file"},
        "canonicalStatePath": "/trusted/project/work/run.state.json", "packageRoot": "../..",
        "resolvedPackageRootRelativePath": "project", "eventLog": "work/events.jsonl",
        "runOutputRootRelativePath": "project/.alk-closing/" + hashlib.sha256(b"run").hexdigest(),
    }
    writes = {"schemaVersion": ALLOWED_WRITES_V1, "bindingId": "binding", "runId": "run",
              "closingWindowId": "window", "outputAnchorDigest": canonical_digest(anchor),
              "entries": list(_CLASSES)}
    writes_raw = canonical_bytes(writes) + b"\n"
    request = {
        "schemaVersion": WINDOW_REQUEST_V1, "scope": deepcopy(grant["scope"]),
        "permission": "closing.activate", "closingWindowId": "window", "predecessorWindowId": None,
        "nonce": grant["nonce"], "expectedWorkflowRevision": 2, "expectedAccountingRevision": 3,
        "validFrom": grant["validFrom"], "expiresAt": grant["expiresAt"],
        "allowedActions": deepcopy(grant["allowedActions"]),
        "allowedWritesRef": {"path": "proof/writes.json", "bytes": len(writes_raw),
                             "sha256": hashlib.sha256(writes_raw).hexdigest()},
        "allowedWritesDigest": canonical_digest(writes),
        "resourceApprovalRef": {"path": "proof/resource.json", "sha256": "4" * 64, "bytes": 120},
        "resourceApprovalDigest": grant["resourceApprovalDigest"],
        "qualifiedPolicyEffectRef": {"path": "proof/candidate.json", "sha256": "5" * 64, "bytes": 120},
        "policyEffectCandidateDigest": "5" * 64, "deadlineInventoryDigest": "6" * 64,
        "deadlineConsumerIds": ["activate"],
        "originalAuthorizationDigest": grant["originalAuthorizationDigest"],
        "originalDeadlineDigest": grant["originalDeadlineDigest"],
        "originalBlockerDigest": grant["originalBlockerDigest"],
    }
    grant["windowIntentDigest"] = canonical_digest(request)
    grant["allowedWritesDigest"] = canonical_digest(writes)
    issuer = {**_issuer(), "allowedWritesDigest": grant["allowedWritesDigest"]}
    snapshot = _signed({
        "schemaVersion": AUTHORITY_SNAPSHOT_V1, "authorityDomain": "authority:run",
        "rootId": "root", "rootGeneration": "generation:1", "bindingId": "binding",
        "journalIdentity": "journal", "epoch": 0, "previousSnapshotDigest": None,
        "validFrom": "2026-09-23T00:00:00.000000Z", "expiresAt": "2026-09-23T04:00:00.000000Z",
        "activeIssuers": [issuer], "revokedIssuers": [], "revokedGrants": [],
    }, bytes(range(32)), _SNAPSHOT_DOMAIN)
    pin = {**_pin(), "expectedInitialSnapshotDigest": canonical_digest(snapshot)}
    grant.update(issuedUnderEpoch=0, issuedUnderSnapshotDigest=canonical_digest(snapshot))
    grant = _signed(grant, bytes(range(1, 33)), _GRANT_DOMAIN)
    request["ownerPermissionRef"] = "sha256:" + canonical_digest(grant)
    selected = {k: deepcopy(request[k]) for k in ["scope", "expectedWorkflowRevision",
                "expectedAccountingRevision", "originalAuthorizationDigest",
                "originalDeadlineDigest", "originalBlockerDigest"]}
    selected["outputAnchorDigest"] = canonical_digest(anchor)
    return {"request": request, "grant": grant, "pin": pin, "issuance": snapshot,
            "current": deepcopy(snapshot), "selected": selected, "allowed_writes_raw": writes_raw,
            "output_anchor": anchor, "observed_at": _OBSERVED}


def _evaluate(fixture: dict) -> dict:
    values = {k: v for k, v in fixture.items() if k != "grant"}
    values["grant_raw"] = canonical_bytes(fixture["grant"])
    return evaluate_window_request_data(**values)


def _rebind_writes_and_signatures(fixture: dict) -> None:
    """Rebind legitimate fixture authority so a later independent join is reached."""
    request, grant = fixture["request"], fixture["grant"]
    grant["allowedWritesDigest"] = request["allowedWritesDigest"]
    grant["windowIntentDigest"] = canonical_digest(window_intent(request))
    issuer = {**_issuer(), "allowedWritesDigest": request["allowedWritesDigest"]}
    snapshot = _signed({**fixture["issuance"], "activeIssuers": [issuer]},
                       bytes(range(32)), _SNAPSHOT_DOMAIN)
    fixture.update(issuance=snapshot, current=deepcopy(snapshot),
                   pin={**fixture["pin"], "expectedInitialSnapshotDigest": canonical_digest(snapshot)})
    grant["issuedUnderSnapshotDigest"] = canonical_digest(snapshot)
    fixture["grant"] = _signed(grant, bytes(range(1, 33)), _GRANT_DOMAIN)
    request["ownerPermissionRef"] = "sha256:" + canonical_digest(fixture["grant"])


def _replace_writes(fixture: dict, writes: dict) -> None:
    raw = canonical_bytes(writes)
    fixture["allowed_writes_raw"] = raw
    fixture["request"]["allowedWritesRef"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    fixture["request"]["allowedWritesDigest"] = canonical_digest(writes)
    _rebind_writes_and_signatures(fixture)


class ClosingWindowSchemaTests(unittest.TestCase):
    def test_wr01_intent_has22_fields_and_signed_request23_without_mutation(self) -> None:
        f = _fixture()
        before = deepcopy(f)
        intent = window_intent(f["request"])
        self.assertEqual(len(intent), 22)
        self.assertEqual(len(f["request"]), 23)
        self.assertNotIn("ownerPermissionRef", intent)
        self.assertEqual(canonical_digest(intent), f["grant"]["windowIntentDigest"])
        self.assertEqual(f["request"]["ownerPermissionRef"], "sha256:" + canonical_digest(f["grant"]))
        self.assertIs(validate_window_intent(intent), intent)
        result = _evaluate(f)
        self.assertEqual(result["status"], "DATA_CANDIDATE")
        self.assertTrue(result["signatureVerified"])
        self.assertEqual(result["requestDigest"], canonical_digest(f["request"]))
        self.assertEqual(f, before)
        for key in ["bootstrapQualified", "historyVerified", "selectedAuthorityVerified",
                    "heldRootIdentityVerified", "clockQualified", "resourcePolicyVerified",
                    "deadlineInputVerified", "nonceConsumed", "nativePermissionGranted",
                    "financialAdmissionGranted", "providerDispatchGranted"]:
            self.assertIs(result[key], False)

    def test_registration_exposes_closed_wire_schemas_and_independent_copies(self) -> None:
        for schema_id, schema in CLOSING_WINDOW_SCHEMAS.items():
            with self.subTest(schema_id=schema_id):
                self.assertEqual(get_schema(schema_id), schema)
                self.assertFalse(schema["additionalProperties"])
                changed = get_schema(schema_id)
                changed["required"].clear()
                self.assertEqual(get_schema(schema_id), schema)

    def test_wr01_raw_duplicate_members_and_byte_limits_refuse_before_normalization(self) -> None:
        f = _fixture()
        raw = canonical_bytes(f["request"])
        self.assertEqual(load_window_request(raw), f["request"])
        self.assertEqual(_evaluate({**f, "request": raw})["status"], "DATA_CANDIDATE")
        for invalid in [raw[:-1] + b',"nonce":"' + b'a' * 64 + b'"}', b'[]',
                        b'{"schemaVersion":NaN}', b'x' * 1_048_577, "{}"]:
            with self.subTest(raw_type=type(invalid).__name__), self.assertRaises(LifecycleError):
                load_window_request(invalid)

    def test_wr01_every_missing_or_extra_request_field_refuses(self) -> None:
        f = _fixture()
        for field in f["request"]:
            changed = deepcopy(f["request"])
            del changed[field]
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                validate_window_request(changed)
        for key in ["currentDeadlineInput", "requestDigest", "nativePermissionGranted"]:
            with self.subTest(extra=key), self.assertRaises(LifecycleError):
                validate_window_request({**f["request"], key: "x"})
        with self.assertRaises(LifecycleError):
            validate_window_intent(f["request"])

    def test_wr01_invalid_wire_values_and_ambiguous_arrays_refuse(self) -> None:
        f = _fixture()
        for field, value in [
            ("schemaVersion", "unsupported"), ("permission", "task.start"),
            ("expectedWorkflowRevision", True), ("expectedAccountingRevision", 3.0),
            ("expectedWorkflowRevision", -1), ("expectedAccountingRevision", 1 << 53),
            ("nonce", "A" * 64), ("policyEffectCandidateDigest", "x" * 64),
            ("ownerPermissionRef", "sha256:" + "a" * 63), ("closingWindowId", ""),
            ("predecessorWindowId", []), ("allowedActions", ["task-start"]),
            ("allowedActions", []), ("allowedActions", ["report", "report"]),
            ("deadlineConsumerIds", [True]), ("deadlineConsumerIds", ["a", "a"]),
        ]:
            with self.subTest(field=field, value=value), self.assertRaises(LifecycleError):
                validate_window_request({**f["request"], field: value})

    def test_wr01_utc_calendar_empty_interval_and_precision_refuse(self) -> None:
        f = _fixture()
        for field, value in [
            ("validFrom", "2026-02-30T01:00:00.000000Z"),
            ("validFrom", "2026-09-23T01:00:00Z"),
            ("validFrom", "2026-09-23T01:00:00.000000+00:00"),
            ("validFrom", f["request"]["expiresAt"]),
            ("expiresAt", f["request"]["validFrom"]),
        ]:
            with self.subTest(field=field, value=value), self.assertRaises(LifecycleError):
                validate_window_request({**f["request"], field: value})

    def test_wr01_artifact_refs_reject_escape_bool_size_and_extensions(self) -> None:
        f = _fixture()
        for field in ["allowedWritesRef", "resourceApprovalRef", "qualifiedPolicyEffectRef"]:
            for change in [{"path": "../escape"}, {"path": "/absolute"}, {"path": "a//b"},
                           {"path": "a/./b"}, {"path": "a\\b"}, {"path": "C:/escape"},
                           {"bytes": True}, {"bytes": 0}, {"bytes": 1_048_577},
                           {"sha256": "invalid"}, {"extension": "x"}]:
                changed = deepcopy(f["request"])
                changed[field].update(change)
                with self.subTest(field=field, change=change), self.assertRaises(LifecycleError):
                    validate_window_request(changed)

    def test_wr02_signed_field_drift_refuses_without_resigning(self) -> None:
        f = _fixture()
        for field in ["nonce", "closingWindowId", "expectedWorkflowRevision", "expectedAccountingRevision",
                      "originalAuthorizationDigest", "originalDeadlineDigest", "originalBlockerDigest",
                      "resourceApprovalDigest", "deadlineInventoryDigest", "policyEffectCandidateDigest",
                      "predecessorWindowId", "allowedActions", "validFrom", "expiresAt"]:
            changed = deepcopy(f)
            old = changed["request"][field]
            new = old + 1 if type(old) is int else "other-window" if old is None else (
                ["report"] if type(old) is list else "0" * 64 if "Digest" in field or field == "nonce"
                else "2026-09-23T01:10:00.000000Z" if field == "validFrom"
                else "2026-09-23T01:50:00.000000Z" if field == "expiresAt" else "other-window")
            changed["request"][field] = new
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                _evaluate(changed)

    def test_wr03_every_selected_scope_revision_and_original_authority_join_refuses(self) -> None:
        f = _fixture()
        for field in f["selected"]:
            changed = deepcopy(f)
            if field == "scope":
                changed["selected"][field]["runId"] = "other-run"
            else:
                old = changed["selected"][field]
                changed["selected"][field] = old + 1 if type(old) is int else "0" * 64
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                _evaluate(changed)
        for field in f["request"]["scope"]:
            changed = deepcopy(f)
            old = changed["request"]["scope"][field]
            changed["request"]["scope"][field] = "0" * 64 if len(old) == 64 else "different"
            with self.subTest(scope_field=field), self.assertRaises(LifecycleError):
                _evaluate(changed)
        for selected in [{}, {**f["selected"], "nativePermissionGranted": True},
                         {**f["selected"], "expectedAccountingRevision": True}]:
            with self.subTest(selected=selected), self.assertRaises(LifecycleError):
                _evaluate({**f, "selected": selected})

    def test_wr02_signature_reference_raw_duplicate_and_current_revocation_refuse(self) -> None:
        f = _fixture()
        changed = deepcopy(f)
        changed["grant"]["signature"]["valueHex"] = "0" * 128
        changed["request"]["ownerPermissionRef"] = "sha256:" + canonical_digest(changed["grant"])
        with self.assertRaises(LifecycleError):
            _evaluate(changed)
        with self.assertRaises(LifecycleError):
            _evaluate({**f, "request": {**f["request"], "ownerPermissionRef": "sha256:" + "0" * 64}})
        raw = canonical_bytes(f["grant"])
        with self.assertRaises(LifecycleError):
            evaluate_window_request_data(**{k: v for k, v in f.items() if k != "grant"},
                                         grant_raw=raw[:-1] + b',"nonce":"' + b'a' * 64 + b'"}')
        changed = deepcopy(f)
        changed["current"] = _signed({**changed["current"], "epoch": 1,
            "previousSnapshotDigest": canonical_digest(f["current"]), "revokedGrants": [{
                "issuerId": "issuer", "issuerGeneration": "generation:1", "nonce": f["grant"]["nonce"]}]},
            bytes(range(32)), _SNAPSHOT_DOMAIN)
        with self.assertRaises(LifecycleError):
            _evaluate(changed)

    def test_wr02_grant_interval_is_inclusive_start_exclusive_end(self) -> None:
        f = _fixture()
        self.assertEqual(_evaluate({**f, "observed_at": f["request"]["validFrom"]})["status"], "DATA_CANDIDATE")
        for now in ["2026-09-23T00:59:59.999999Z", f["request"]["expiresAt"],
                    "2026-09-23T02:00:00.000001Z"]:
            with self.subTest(now=now), self.assertRaises(LifecycleError):
                _evaluate({**f, "observed_at": now})

    def test_wr06_allowed_writes_are_sorted_unique_complete_and_raw_bound(self) -> None:
        f = _fixture()
        writes = {"schemaVersion": ALLOWED_WRITES_V1, "bindingId": "binding", "runId": "run",
                  "closingWindowId": "window", "outputAnchorDigest": f["selected"]["outputAnchorDigest"],
                  "entries": list(_CLASSES)}
        self.assertIs(validate_allowed_writes(writes), writes)
        for entries in [[], _CLASSES[::-1], _CLASSES + [_CLASSES[0]], ["OTHER"], [True]]:
            with self.subTest(entries=entries), self.assertRaises(LifecycleError):
                validate_allowed_writes({**writes, "entries": entries})
        for raw in [f["allowed_writes_raw"] + b" ", b"{}", b"x" * 1_048_577]:
            with self.subTest(size=len(raw)), self.assertRaises(LifecycleError):
                _evaluate({**f, "allowed_writes_raw": raw})
        # Rebind request and both signatures: raw/intent validity must not permit a partial write set.
        partial = {**writes, "entries": _CLASSES[:-1]}
        changed = deepcopy(f)
        changed["allowed_writes_raw"] = canonical_bytes(partial)
        changed["request"]["allowedWritesRef"] = {"path": "proof/writes.json",
            "bytes": len(changed["allowed_writes_raw"]),
            "sha256": hashlib.sha256(changed["allowed_writes_raw"]).hexdigest()}
        changed["request"]["allowedWritesDigest"] = canonical_digest(partial)
        changed["grant"]["allowedWritesDigest"] = canonical_digest(partial)
        changed["grant"]["windowIntentDigest"] = canonical_digest(window_intent(changed["request"]))
        issuer = {**_issuer(), "allowedWritesDigest": canonical_digest(partial)}
        snapshot = _signed({**f["issuance"], "activeIssuers": [issuer]}, bytes(range(32)), _SNAPSHOT_DOMAIN)
        changed.update(issuance=snapshot, current=deepcopy(snapshot),
                       pin={**f["pin"], "expectedInitialSnapshotDigest": canonical_digest(snapshot)})
        changed["grant"]["issuedUnderSnapshotDigest"] = canonical_digest(snapshot)
        changed["grant"] = _signed(changed["grant"], bytes(range(1, 33)), _GRANT_DOMAIN)
        changed["request"]["ownerPermissionRef"] = "sha256:" + canonical_digest(changed["grant"])
        with self.assertRaises(LifecycleError):
            _evaluate(changed)

    def test_wr06_anchor_identity_root_path_and_run_derivation_refuse_drift(self) -> None:
        f = _fixture()
        self.assertIs(validate_run_output_anchor(f["output_anchor"]), f["output_anchor"])
        for field, value in [("runId", "other"), ("journalIdentity", "other"),
                             ("adoptedStateDigest", "0" * 64), ("bindingDigest", "0" * 64),
                             ("eventLog", "work/other.jsonl"), ("packageRoot", "other"),
                             ("artifactAuthorityRootPath", "/different")]:
            changed = deepcopy(f)
            changed["output_anchor"][field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                _evaluate(changed)
        for field, value in [("canonicalStatePath", "/outside/state.json"),
                             ("canonicalStatePath", "/trusted/project/../state.json"),
                             ("artifactAuthorityRootPath", "/trusted//root"),
                             ("canonicalStatePath", "/trusted/project/./state.json"),
                             ("eventLog", "../events"), ("eventLog", "/events"),
                             ("runOutputRootRelativePath", "wrong"),
                             ("storageProtocolVersion", 6)]:
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                validate_run_output_anchor({**f["output_anchor"], field: value})
        for identity in [{}, {"platform": [], "volumeId": "v", "fileId": "f"},
                         {"platform": "POSIX", "volumeId": "v", "fileId": "f", "extra": True}]:
            with self.subTest(identity=identity), self.assertRaises(LifecycleError):
                validate_run_output_anchor({**f["output_anchor"], "artifactAuthorityRootIdentity": identity})

    def test_wr06_windows_and_root_relative_anchor_are_data_only(self) -> None:
        anchor = _fixture()["output_anchor"]
        windows = {**anchor, "artifactAuthorityRootPath": "C:\\trusted",
                   "canonicalStatePath": "C:\\trusted\\project\\work\\run.state.json",
                   "artifactAuthorityRootIdentity": {"platform": "WINDOWS", "volumeId": "v", "fileId": "f"}}
        self.assertIs(validate_run_output_anchor(windows), windows)
        with self.assertRaises(LifecycleError):
            validate_run_output_anchor({**windows, "canonicalStatePath": "D:\\elsewhere\\state"})
        root_relative = {**anchor, "resolvedPackageRootRelativePath": ".",
                         "runOutputRootRelativePath": ".alk-closing/" + hashlib.sha256(b"run").hexdigest()}
        self.assertIs(validate_run_output_anchor(root_relative), root_relative)


    def test_r718_m01_raw_digest_scope_and_anchor_guards_are_isolated(self) -> None:
        import json
        f = _fixture()
        same_length = f["allowed_writes_raw"][:-1] + b" "
        self.assertEqual(len(same_length), len(f["allowed_writes_raw"]))
        self.assertEqual(json.loads(same_length), json.loads(f["allowed_writes_raw"]))
        with self.assertRaises(LifecycleError) as caught:
            _evaluate({**f, "allowed_writes_raw": same_length})
        self.assertEqual(caught.exception.message, "AllowedWrites raw identity differs")
        changed = deepcopy(f)
        changed["request"]["allowedWritesDigest"] = "0" * 64
        _rebind_writes_and_signatures(changed)
        self.assertEqual(changed["allowed_writes_raw"], f["allowed_writes_raw"])
        with self.assertRaises(LifecycleError) as caught:
            _evaluate(changed)
        self.assertEqual(caught.exception.message, "AllowedWrites canonical digest differs")
        for field in ("bindingId", "runId", "closingWindowId", "outputAnchorDigest"):
            with self.subTest(writes_field=field):
                changed = deepcopy(f)
                writes = json.loads(f["allowed_writes_raw"])
                writes[field] = "0" * 64 if field == "outputAnchorDigest" else "other"
                _replace_writes(changed, writes)
                with self.assertRaises(LifecycleError) as caught:
                    _evaluate(changed)
                expected = ("Output anchor is not the independently selected data"
                            if field == "outputAnchorDigest" else "AllowedWrites scope/window differs")
                self.assertEqual(caught.exception.message, expected)
        for field in ("runId", "journalIdentity"):
            with self.subTest(anchor_field=field):
                changed = deepcopy(f)
                changed["output_anchor"][field] = "other"
                if field == "runId":
                    changed["output_anchor"]["runOutputRootRelativePath"] = (
                        "project/.alk-closing/" + hashlib.sha256(b"other").hexdigest())
                digest = canonical_digest(changed["output_anchor"])
                changed["selected"]["outputAnchorDigest"] = digest
                writes = json.loads(f["allowed_writes_raw"])
                writes["outputAnchorDigest"] = digest
                _replace_writes(changed, writes)
                with self.assertRaises(LifecycleError) as caught:
                    _evaluate(changed)
                self.assertEqual(caught.exception.message, "Output anchor run/journal differs")

    def test_r718_m02_signed_contradictions_preserve_request_and_selected(self) -> None:
        f = _fixture()
        fields = [("scope", name) for name in f["grant"]["scope"]]
        fields += [(name, None) for name in ("expectedWorkflowRevision", "originalAuthorizationDigest",
                                             "originalDeadlineDigest", "originalBlockerDigest")]
        for field, scope_field in fields:
            with self.subTest(grant_field=field, scope_field=scope_field):
                changed = deepcopy(f)
                if field == "scope":
                    old = changed["grant"][field][scope_field]
                    changed["grant"][field][scope_field] = "0" * 64 if len(old) == 64 else "other"
                elif field == "expectedWorkflowRevision":
                    changed["grant"][field] += 1
                else:
                    changed["grant"][field] = "0" * 64
                changed["grant"] = _signed(changed["grant"], bytes(range(1, 33)), _GRANT_DOMAIN)
                changed["request"]["ownerPermissionRef"] = "sha256:" + canonical_digest(changed["grant"])
                self.assertEqual(window_intent(changed["request"]), window_intent(f["request"]))
                self.assertEqual(changed["selected"], f["selected"])
                self.assertEqual(changed["grant"]["windowIntentDigest"],
                                 canonical_digest(window_intent(changed["request"])))
                with self.assertRaises(LifecycleError) as caught:
                    _evaluate(changed)
                expected = ("Grant or issuer scope differs from selected run binding"
                            if field == "scope" else "Request differs from the signed grant")
                self.assertEqual(caught.exception.message, expected)

    def test_r718_m03_current_snapshot_expiry_and_issuer_loss_are_isolated(self) -> None:
        f = _fixture()
        def current_snapshot(**changes):
            return _signed({**f["current"], "epoch": 1,
                            "previousSnapshotDigest": canonical_digest(f["current"]), **changes},
                           bytes(range(32)), _SNAPSHOT_DOMAIN)
        valid = current_snapshot(expiresAt="2026-09-23T02:00:00.000000Z")
        positive = _evaluate({**f, "current": valid})
        self.assertEqual(positive["status"], "DATA_CANDIDATE")
        self.assertFalse(positive["historyVerified"])
        self.assertFalse(positive["clockQualified"])
        controls = [(current_snapshot(expiresAt="2026-09-23T01:15:00.000000Z"),
                     "Snapshot is not valid at observation"),
                    (current_snapshot(activeIssuers=[]), "Grant issuer is not active")]
        issuer = deepcopy(f["current"]["activeIssuers"][0])
        issuer["allowedActions"] = issuer["allowedActions"][:-1]
        controls.append((current_snapshot(activeIssuers=[issuer]), "Issuer permission changed"))
        for snapshot, expected in controls:
            with self.subTest(expected=expected), self.assertRaises(LifecycleError) as caught:
                _evaluate({**f, "current": snapshot})
            self.assertEqual(caught.exception.message, expected)
        self.assertEqual(f["grant"]["validFrom"], "2026-09-23T01:00:00.000000Z")
        self.assertEqual(f["grant"]["expiresAt"], "2026-09-23T02:00:00.000000Z")

    def test_r718_l01_valid_json_boundary_and_overflow_refuse_by_size(self) -> None:
        f = _fixture()
        compact = canonical_bytes(f["request"])
        boundary = compact + b" " * (1_048_576 - len(compact))
        self.assertEqual(len(boundary), 1_048_576)
        self.assertEqual(load_window_request(boundary), f["request"])
        with self.assertRaises(LifecycleError) as caught:
            load_window_request(boundary + b" ")
        self.assertEqual(caught.exception.code, "json-input-too-large")


if __name__ == "__main__":
    unittest.main()
