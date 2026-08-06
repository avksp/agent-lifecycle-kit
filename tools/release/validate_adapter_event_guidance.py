from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from release_common import digest_value, load_json, write_json

from agent_lifecycle.host_protocol import adapter_declares_event_capture, validate_event_capture_conformance

DOC_REQUIRED_MARKER_GROUPS = (
    ("adapter-owned",),
    ("agent-adapter-event.v1",),
    ("agent-adapter-event-stream-receipt.v1",),
    ("No automatic hook installation", "Автоматическая установка: нет"),
)

EVENT_BRIDGE_REQUIRED_MARKER_GROUPS = (
    ("adapter-owned",),
    ("operator-owned",),
    ("agent-adapter-event.v1",),
    ("agent-adapter-event-stream-receipt.v1",),
    ("No automatic hook installation",),
)

BANNED_HOOK_CLAIMS = (
    "alk installs hooks",
    "alk installs host hooks",
    "core installs hooks",
    "core-owned hook installation",
    "alk-owned hook installation",
    "automatic hook installation: yes",
)

EXAMPLE_ADAPTERS = ("codex", "claude", "opencode")


def validate_adapter_event_guidance(root: Path) -> dict[str, Any]:
    adapter_results = [_validate_adapter(root, path.parent.name) for path in sorted((root / "adapters").glob("*/adapter.descriptor.json"))]
    docs_results = _validate_docs(root, adapter_results)
    blockers = [blocker for result in adapter_results for blocker in result["blockers"]]
    blockers.extend(docs_results["blockers"])
    body = {
        "schemaVersion": "agent-adapter-event-guidance-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "adapterCount": len(adapter_results),
        "declaredAdapterCount": sum(1 for result in adapter_results if result["declaredEventCapture"]),
        "adapterResults": adapter_results,
        "docs": docs_results,
        "blockers": blockers,
        "hostCallsStarted": False,
        "modelCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _validate_adapter(root: Path, adapter_id: str) -> dict[str, Any]:
    descriptor_path = root / "adapters" / adapter_id / "adapter.descriptor.json"
    capability_path = root / "adapters" / adapter_id / "capabilities.manifest.json"
    event_stream_path = root / "conformance" / "adapters" / adapter_id / "event-stream.json"
    receipt_path = root / "conformance" / "adapters" / adapter_id / "event-stream-receipt.json"
    descriptor = load_json(descriptor_path)
    capability_manifest = load_json(capability_path) if capability_path.is_file() else None
    declared = adapter_declares_event_capture(descriptor=descriptor, capability_manifest=capability_manifest)
    blockers: list[dict[str, Any]] = []
    conformance: dict[str, Any] | None = None
    if declared:
        if not event_stream_path.is_file():
            blockers.append(_blocker("adapter-event-stream-doc-route-missing", adapter_id, event_stream_path))
        if not receipt_path.is_file():
            blockers.append(_blocker("adapter-event-receipt-route-missing", adapter_id, receipt_path))
        if event_stream_path.is_file() and receipt_path.is_file():
            events = _load_event_stream(event_stream_path)
            receipt = load_json(receipt_path)
            conformance = validate_event_capture_conformance(
                descriptor=descriptor,
                capability_manifest=capability_manifest,
                events=events,
                receipt=receipt,
            )
            if conformance["status"] != "PASS":
                blockers.append({"code": "adapter-event-conformance-failed", "adapterId": adapter_id, "validation": conformance})
    return {
        "adapterId": adapter_id,
        "declaredEventCapture": declared,
        "descriptor": descriptor_path.as_posix(),
        "capabilityManifest": capability_path.as_posix() if capability_path.is_file() else None,
        "eventStream": event_stream_path.as_posix() if event_stream_path.is_file() else None,
        "receipt": receipt_path.as_posix() if receipt_path.is_file() else None,
        "conformanceStatus": conformance.get("status") if isinstance(conformance, dict) else None,
        "blockers": blockers,
    }


def _validate_docs(root: Path, adapter_results: list[dict[str, Any]]) -> dict[str, Any]:
    declared_ids = [result["adapterId"] for result in adapter_results if result["declaredEventCapture"]]
    docs = [
        root / "docs" / "adapters" / "event-capture-matrix.md",
        root / "docs" / "ru" / "adapters" / "event-capture-matrix.md",
        root / "docs" / "reference" / "adapter-event-capture.md",
        root / "docs" / "ru" / "reference" / "adapter-event-capture.md",
        root / "docs" / "adapters" / "support-matrix.md",
        root / "docs" / "ru" / "adapters" / "support-matrix.md",
    ]
    blockers: list[dict[str, Any]] = []
    for path in docs:
        if not path.is_file():
            blockers.append({"code": "adapter-event-guidance-doc-missing", "path": path.as_posix()})
            continue
        text = path.read_text(encoding="utf-8")
        for markers in DOC_REQUIRED_MARKER_GROUPS:
            if not any(marker in text for marker in markers):
                blockers.append({"code": "adapter-event-guidance-marker-missing", "path": path.as_posix(), "marker": " | ".join(markers)})
        blockers.extend(_banned_claim_blockers(path, text))
    matrix_text = (root / "docs" / "adapters" / "event-capture-matrix.md").read_text(encoding="utf-8") if (root / "docs" / "adapters" / "event-capture-matrix.md").is_file() else ""
    ru_matrix_text = (root / "docs" / "ru" / "adapters" / "event-capture-matrix.md").read_text(encoding="utf-8") if (root / "docs" / "ru" / "adapters" / "event-capture-matrix.md").is_file() else ""
    for adapter_id in declared_ids:
        if f"| {adapter_id} " not in matrix_text and f"| `{adapter_id}` " not in matrix_text:
            blockers.append({"code": "adapter-event-matrix-row-missing", "adapterId": adapter_id, "path": "docs/adapters/event-capture-matrix.md"})
        if f"| {adapter_id} " not in ru_matrix_text and f"| `{adapter_id}` " not in ru_matrix_text:
            blockers.append({"code": "adapter-event-matrix-row-missing", "adapterId": adapter_id, "path": "docs/ru/adapters/event-capture-matrix.md"})
    for adapter_id in EXAMPLE_ADAPTERS:
        path = root / "adapters" / adapter_id / "event-bridge.md"
        if not path.is_file():
            blockers.append({"code": "adapter-event-bridge-doc-missing", "adapterId": adapter_id, "path": path.as_posix()})
            continue
        text = path.read_text(encoding="utf-8")
        for markers in EVENT_BRIDGE_REQUIRED_MARKER_GROUPS:
            if not any(marker in text for marker in markers):
                blockers.append({"code": "adapter-event-bridge-marker-missing", "adapterId": adapter_id, "path": path.as_posix(), "marker": " | ".join(markers)})
        blockers.extend(_banned_claim_blockers(path, text))
    return {
        "schemaVersion": "agent-adapter-event-guidance-docs-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "declaredAdapters": declared_ids,
        "checkedDocs": [path.as_posix() for path in docs],
        "exampleAdapters": list(EXAMPLE_ADAPTERS),
        "blockers": blockers,
    }


def _load_event_stream(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SystemExit(f"expected event stream JSON array: {path}")
    return value


def _banned_claim_blockers(path: Path, text: str) -> list[dict[str, Any]]:
    lower = text.lower()
    return [
        {"code": "adapter-event-core-owned-hook-claim", "path": path.as_posix(), "marker": marker}
        for marker in BANNED_HOOK_CLAIMS
        if marker in lower
    ]


def _blocker(code: str, adapter_id: str, path: Path) -> dict[str, Any]:
    return {"code": code, "adapterId": adapter_id, "path": path.as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    payload = validate_adapter_event_guidance(Path(args.root))
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
