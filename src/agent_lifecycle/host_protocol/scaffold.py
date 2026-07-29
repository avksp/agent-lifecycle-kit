"""Adapter projection scaffold generation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, sha256_hex, write_json_create
from agent_lifecycle.host_protocol.capabilities import build_capability_manifest
from agent_lifecycle.host_protocol.validation import REQUIRED_OPERATION_NAMES

HOST_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


@dataclass(frozen=True)
class ScaffoldFile:
    path: Path
    role: str
    payload: dict[str, Any] | str


def scaffold_adapter(
    *,
    host: str,
    target: Path,
    maturity: str = "EXPERIMENTAL",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create an EXPERIMENTAL adapter projection skeleton under target."""

    _validate_options(host=host, maturity=maturity)
    files = _scaffold_files(host, target)
    conflicts = [item.path.as_posix() for item in files if item.path.exists()]
    if conflicts:
        raise LifecycleError("adapter-scaffold-target-exists", "adapter scaffold target already contains generated files", {"paths": conflicts})
    records = [_file_record(item) for item in files]
    if not dry_run:
        for item in files:
            if isinstance(item.payload, str):
                _write_text_create(item.path, item.payload)
            else:
                write_json_create(item.path, item.payload)
    return {
        "schemaVersion": "agent-adapter-scaffold-result.v1",
        "status": "DRY_RUN" if dry_run else "PASS",
        "host": host,
        "target": target.as_posix(),
        "maturity": maturity,
        "files": records,
        "productionPromotionClaimed": False,
    }


def _validate_options(*, host: str, maturity: str) -> None:
    if not HOST_ID_RE.fullmatch(host):
        raise LifecycleError("invalid-adapter-host", "adapter host id must match ^[a-z][a-z0-9-]{1,31}$")
    if maturity != "EXPERIMENTAL":
        raise LifecycleError("adapter-scaffold-verified-forbidden", "adapter scaffold can only create EXPERIMENTAL projections")


def _scaffold_files(host: str, target: Path) -> list[ScaffoldFile]:
    descriptor_path = target / "adapters" / host / "adapter.descriptor.json"
    capability_path = target / "adapters" / host / "capabilities.manifest.json"
    projection_path = target / "adapters" / host / "projection.manifest.json"
    event_bridge_path = target / "adapters" / host / "event-bridge.md"
    runner_path = target / "adapters" / host / "runner.py"
    receipt_normalizer_path = target / "adapters" / host / "receipt_normalizer.py"
    validation_path = target / "adapters" / host / "validation.md"
    conformance_path = target / "conformance" / "adapters" / host / "offline-baseline.json"
    docs_path = target / "docs" / "adapters" / f"{host}.md"
    support_stub_path = target / "docs" / "adapters" / f"{host}.support.md"
    test_path = target / "tests" / "adapters" / host / f"test_{host.replace('-', '_')}_adapter.py"
    descriptor = _descriptor(host)
    return [
        ScaffoldFile(descriptor_path, "adapter-descriptor", descriptor),
        ScaffoldFile(capability_path, "capability-manifest", build_capability_manifest(descriptor)),
        ScaffoldFile(
            projection_path,
            "projection-manifest",
            _projection_manifest(
                host=host,
                descriptor_path=descriptor_path,
                capability_path=capability_path,
                conformance_path=conformance_path,
                docs_path=docs_path,
                event_bridge_path=event_bridge_path,
                runner_path=runner_path,
                receipt_normalizer_path=receipt_normalizer_path,
                validation_path=validation_path,
            ),
        ),
        ScaffoldFile(event_bridge_path, "event-bridge-placeholder", _event_bridge(host)),
        ScaffoldFile(runner_path, "runner-skeleton", _runner(host)),
        ScaffoldFile(receipt_normalizer_path, "receipt-normalizer", _receipt_normalizer(host)),
        ScaffoldFile(validation_path, "validation-instructions", _validation(host)),
        ScaffoldFile(conformance_path, "offline-conformance-baseline", _offline_baseline(host, descriptor_path)),
        ScaffoldFile(docs_path, "adapter-doc", _docs(host)),
        ScaffoldFile(support_stub_path, "support-matrix-stub", _support_stub(host)),
        ScaffoldFile(test_path, "adapter-test-skeleton", _test_skeleton(host)),
    ]


def _descriptor(host: str) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-lifecycle-host-adapter.v1",
        "adapterId": host,
        "host": host,
        "nativeProjection": "host-local-projection",
        "capabilityManifest": f"adapters/{host}/capabilities.manifest.json",
        "maturity": "EXPERIMENTAL",
        "liveTestedHostRange": None,
        "contractCompatibility": {
            "rangeKind": "closed-offline",
            "minimum": "adapter-contract.v1",
            "maximum": "adapter-contract.v1",
            "authoritativeSource": {
                "sourceId": "normalized-contract-inventory-r02",
                "sha256": "c332a29de6eed7dcf1ff93cfa5cb0868557f31d1f7ff635ba2df2c7695ed3d4a",
            },
        },
        "unsupportedOperationPolicy": "fail-closed",
        "coreSemantics": "delegated-to-agent-lifecycle-core",
        "modelRouting": {
            "status": "workflow-enforced",
            "profileSupport": "host-local",
            "providerModelNamesInCore": False,
            "attemptRoutePolicy": "must-execute-or-fail-closed",
            "usageReceiptRequired": True,
            "unsupportedClassPolicy": "fail-closed",
            "criticalReviewPolicy": "requires-strong-or-calibrated-local-review",
            "liveVerified": False,
        },
        "operations": [
            {
                "name": name,
                "mapping": "host-local-fail-closed",
                "offlineConformance": "synthetic",
            }
            for name in sorted(REQUIRED_OPERATION_NAMES)
        ],
    }


def _projection_manifest(
    *,
    host: str,
    descriptor_path: Path,
    capability_path: Path,
    conformance_path: Path,
    docs_path: Path,
    event_bridge_path: Path,
    runner_path: Path,
    receipt_normalizer_path: Path,
    validation_path: Path,
) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-adapter-projection-manifest.v1",
        "host": host,
        "maturity": "EXPERIMENTAL",
        "descriptor": descriptor_path.as_posix(),
        "capabilityManifest": capability_path.as_posix(),
        "offlineBaseline": conformance_path.as_posix(),
        "docs": docs_path.as_posix(),
        "eventBridge": {
            "path": event_bridge_path.as_posix(),
            "status": "placeholder",
            "portableEventSchema": "agent-adapter-event.v1",
            "runtimeDispatch": "not-implemented-fail-closed",
        },
        "runner": {
            "path": runner_path.as_posix(),
            "status": "fail-closed-skeleton",
        },
        "receiptNormalizer": {
            "path": receipt_normalizer_path.as_posix(),
            "status": "contract-normalization-skeleton",
            "portableReceiptSchema": "agent-host-operation-receipt.v1",
        },
        "validation": {
            "path": validation_path.as_posix(),
            "descriptorCommand": f"agent-lifecycle adapter validate --descriptor adapters/{host}/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json",
            "inspectCommand": f"agent-lifecycle adapter inspect --descriptor adapters/{host}/adapter.descriptor.json --skip-host-commands",
            "supportMatrixCommand": "python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json --evidence <support-matrix-evidence.json>",
        },
        "providerModelNamesInCore": False,
        "productionPromotionClaimed": False,
        "publicDirectoryApprovalClaimed": False,
    }


def _offline_baseline(host: str, descriptor_path: Path) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-lifecycle-adapter-conformance.v1",
        "adapterId": host,
        "host": host,
        "baselineId": "offline-adapter-baseline-v1",
        "adapterDescriptor": descriptor_path.as_posix(),
        "capabilityManifest": descriptor_path.with_name("capabilities.manifest.json").as_posix(),
        "nativeManifest": None,
        "sharedBaseline": "conformance/core/adapter-baseline.v1.json",
        "requiredMaturity": "EXPERIMENTAL",
        "liveRuntimeRequired": False,
        "expectedResult": "PASS",
    }


def _event_bridge(host: str) -> str:
    return (
        f"# {host} event bridge\n\n"
        "This is an EXPERIMENTAL event bridge placeholder. A real host adapter\n"
        "must translate host lifecycle callbacks into `agent-adapter-event.v1`\n"
        "records and validate them with `agent-lifecycle adapter event-check`.\n\n"
        "The scaffold does not implement runtime dispatch. Unsupported operations\n"
        "must fail closed until host-specific live conformance evidence exists.\n"
    )


def _runner(host: str) -> str:
    return (
        '"""Fail-closed runner skeleton for the adapter projection."""\n\n'
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n"
        "from agent_lifecycle.contracts import LifecycleError\n\n\n"
        "def run_operation(request: dict[str, Any]) -> dict[str, Any]:\n"
        "    capability = request.get(\"capability\")\n"
        "    raise LifecycleError(\n"
        "        \"adapter-operation-not-implemented\",\n"
        f"        \"{host} adapter runner is not implemented for live execution\",\n"
        f"        {{\"host\": \"{host}\", \"capability\": capability}},\n"
        "    )\n"
    )


def _receipt_normalizer(host: str) -> str:
    return (
        '"""Receipt normalizer for the adapter projection."""\n\n'
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n"
        "from agent_lifecycle.host_protocol import normalize_host_operation_receipt\n\n\n"
        "def normalize_receipt(payload: dict[str, Any]) -> dict[str, Any]:\n"
        f"    \"\"\"Normalize one {host} host receipt into the portable contract.\"\"\"\n"
        "    return normalize_host_operation_receipt(payload)\n"
    )


def _validation(host: str) -> str:
    return (
        f"# {host} validation\n\n"
        "Minimum offline checks before committing the projection:\n\n"
        "```bash\n"
        f"agent-lifecycle adapter validate --descriptor adapters/{host}/adapter.descriptor.json --baseline conformance/core/adapter-baseline.v1.json\n"
        f"agent-lifecycle adapter inspect --descriptor adapters/{host}/adapter.descriptor.json --skip-host-commands\n"
        "agent-lifecycle adapter event-check --event <adapter-event-1.json> --event <adapter-event-2.json>\n"
        "python tools/release/validate_support_matrix.py --support-matrix docs/adapters/support-matrix.md --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json --evidence <support-matrix-evidence.json>\n"
        "```\n\n"
        "These checks prove only an EXPERIMENTAL source projection. Promotion to\n"
        "`VERIFIED` requires bounded live host conformance, live calibration,\n"
        "and lifecycle proof evidence bound to the tested host version.\n"
    )


def _docs(host: str) -> str:
    return (
        f"# {host} adapter\n\n"
        "This scaffold is an EXPERIMENTAL host projection skeleton. It contains\n"
        "no lifecycle semantics, no concrete provider model names, and no\n"
        "`VERIFIED` or production-promotion claim.\n\n"
        "Before promotion, add host-local runtime evidence and validate it through\n"
        "the release support matrix, live host conformance validator, live\n"
        "calibration validator, and final lifecycle proof.\n"
    )


def _support_stub(host: str) -> str:
    return (
        f"# {host} support matrix stub\n\n"
        "Initial maturity: `EXPERIMENTAL`.\n\n"
        "Do not claim `VERIFIED`, public directory approval, or production\n"
        "promotion until bounded live host conformance, usage calibration,\n"
        "redaction scan, and support-matrix review all pass for a concrete host\n"
        "version range.\n"
    )


def _test_skeleton(host: str) -> str:
    return (
        "from __future__ import annotations\n\n"
        "import json\n"
        "from pathlib import Path\n\n"
        "from agent_lifecycle.host_protocol import build_capability_manifest, validate_adapter_descriptor, validate_capability_manifest\n\n\n"
        "ROOT = Path(__file__).resolve().parents[3]\n\n\n"
        "def test_descriptor_and_capability_manifest_pass_offline_contracts() -> None:\n"
        f"    descriptor_path = ROOT / \"adapters/{host}/adapter.descriptor.json\"\n"
        "    descriptor = json.loads(descriptor_path.read_text(encoding=\"utf-8\"))\n"
        "    baseline = json.loads((ROOT / \"conformance/core/adapter-baseline.v1.json\").read_text(encoding=\"utf-8\"))\n"
        "    manifest = build_capability_manifest(descriptor)\n\n"
        "    assert validate_adapter_descriptor(descriptor, baseline=baseline)[\"status\"] == \"PASS\"\n"
        "    assert validate_capability_manifest(manifest, descriptor=descriptor)[\"status\"] == \"PASS\"\n"
        f"    assert manifest[\"adapterId\"] == \"{host}\"\n"
    )


def _file_record(item: ScaffoldFile) -> dict[str, Any]:
    payload = item.payload
    data = payload.encode("utf-8") if isinstance(payload, str) else canonical_bytes(payload) + b"\n"
    return {
        "path": item.path.as_posix(),
        "role": item.role,
        "sha256": sha256_hex(data),
    }


def _write_text_create(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o644), "w", encoding="utf-8") as handle:
        handle.write(text)
