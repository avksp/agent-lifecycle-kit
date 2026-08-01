"""Draft-only task template helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

TASK_TEMPLATE_LIBRARY_SCHEMA = "agent-task-template-library.v1"
TASK_TEMPLATE_LIBRARY_VALIDATION_SCHEMA = "agent-task-template-library-validation.v1"
TASK_TEMPLATE_RENDER_SCHEMA = "agent-task-template-render.v1"
MAX_TEMPLATE_BYTES = 32768
MAX_VARIABLE_CHARS = 500

_REQUIRED_MARKERS = (
    "Template status: DRAFT-ONLY.",
    "Review gate: required.",
    "Freeze gate: required.",
    "Runtime defaults: none.",
)
_FORBIDDEN_MARKERS = (
    "enabledByDefault: true",
    "productionPromotionClaimed: true",
    "providerDefault",
    "modelDefault",
    "api" "_key",
    "api" "Key",
)

_TEMPLATE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "templateId": "bugfix",
        "title": "Bugfix",
        "path": "templates/tasks/bugfix.md",
        "taskShape": "bugfix",
        "qualityProfiles": ["bug-forensics"],
        "placeholders": [
            "bug_summary",
            "failing_command",
            "expected_behavior",
            "observed_behavior",
            "suspect_scope",
        ],
    },
    {
        "templateId": "idea-to-pr",
        "title": "Idea To PR",
        "path": "templates/tasks/idea-to-pr.md",
        "taskShape": "feature",
        "qualityProfiles": [],
        "placeholders": [
            "goal",
            "current_behavior",
            "desired_behavior",
            "constraints",
            "validation_target",
        ],
    },
    {
        "templateId": "pr-review",
        "title": "PR Review",
        "path": "templates/tasks/pr-review.md",
        "taskShape": "review",
        "qualityProfiles": [],
        "placeholders": ["change_ref", "base_ref", "review_focus", "required_checks"],
    },
    {
        "templateId": "merge-conflict-repair",
        "title": "Merge Conflict Repair",
        "path": "templates/tasks/merge-conflict-repair.md",
        "taskShape": "merge-conflict-repair",
        "qualityProfiles": [],
        "placeholders": ["source_branch", "target_branch", "conflict_files", "preserved_behavior"],
    },
    {
        "templateId": "release-readiness",
        "title": "Release Readiness",
        "path": "templates/tasks/release-readiness.md",
        "taskShape": "release-readiness",
        "qualityProfiles": [],
        "placeholders": ["release_version", "candidate_branch", "required_gates", "known_risks"],
    },
)


def build_task_template_library() -> dict[str, Any]:
    """Return the built-in draft-only task template catalog."""

    templates = [_template_record(spec) for spec in _TEMPLATE_SPECS]
    body = {
        "schemaVersion": TASK_TEMPLATE_LIBRARY_SCHEMA,
        "status": "OPTIONAL",
        "enabledByDefault": False,
        "activationMode": "explicit-template-selection",
        "draftOnly": True,
        "requiresReview": True,
        "freezeBlocked": True,
        "defaultCommandFootprint": {
            "extraCommands": 0,
            "extraLiveCalls": 0,
            "extraRequiredArtifacts": 0,
        },
        "templates": templates,
        "productionPromotionClaimed": False,
    }
    return {**body, "libraryDigest": canonical_digest(body)}


def validate_task_template_library(
    *,
    project_root: Path = Path("."),
    library: dict[str, Any] | None = None,
    template_id: str | None = None,
) -> dict[str, Any]:
    """Validate the built-in template catalog and markdown files."""

    selected_library = library or build_task_template_library()
    blockers: list[dict[str, Any]] = []
    if selected_library.get("schemaVersion") != TASK_TEMPLATE_LIBRARY_SCHEMA:
        blockers.append({"code": "task-template-library-schema-invalid"})
    if selected_library.get("status") != "OPTIONAL":
        blockers.append({"code": "task-template-library-status-invalid"})
    if selected_library.get("enabledByDefault") is not False:
        blockers.append({"code": "task-template-library-default-enabled"})
    if selected_library.get("activationMode") != "explicit-template-selection":
        blockers.append({"code": "task-template-library-activation-invalid"})
    if selected_library.get("draftOnly") is not True:
        blockers.append({"code": "task-template-library-not-draft-only"})
    if selected_library.get("requiresReview") is not True or selected_library.get("freezeBlocked") is not True:
        blockers.append({"code": "task-template-library-gates-missing"})
    if selected_library.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "task-template-library-production-claim"})
    if selected_library.get("libraryDigest") != canonical_digest(_without_digest(selected_library, "libraryDigest")):
        blockers.append({"code": "task-template-library-digest-mismatch"})

    templates = selected_library.get("templates")
    if not isinstance(templates, list) or not templates:
        blockers.append({"code": "task-template-library-empty"})
        templates = []
    selected_templates = [item for item in templates if template_id is None or item.get("templateId") == template_id]
    if template_id is not None and not selected_templates:
        blockers.append({"code": "task-template-id-unknown", "templateId": template_id})

    reports = [
        _validate_template_record(project_root, item, index=index)
        for index, item in enumerate(selected_templates)
        if isinstance(item, dict)
    ]
    for report in reports:
        blockers.extend(report["blockers"])

    body = {
        "schemaVersion": TASK_TEMPLATE_LIBRARY_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "templateCount": len(selected_templates),
        "templateIds": [item.get("templateId") for item in selected_templates if isinstance(item, dict)],
        "reports": reports,
        "blockers": blockers,
        "libraryDigest": selected_library.get("libraryDigest"),
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def render_task_template(
    template_id: str,
    *,
    project_root: Path = Path("."),
    variables: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Render one draft-only template with optional declared placeholder values."""

    spec = _template_spec(template_id)
    values = variables or {}
    blockers = _validate_variables(spec, values)
    path = project_root / spec["path"]
    content = ""
    if not path.is_file():
        blockers.append({"code": "task-template-file-missing", "path": spec["path"]})
    elif path.stat().st_size > MAX_TEMPLATE_BYTES:
        blockers.append({"code": "task-template-file-too-large", "path": spec["path"]})
    else:
        content = path.read_text(encoding="utf-8")
        for key, value in values.items():
            content = content.replace("{{" + key + "}}", value)
        blockers.extend(_template_text_blockers(content, template_id=template_id))

    body = {
        "schemaVersion": TASK_TEMPLATE_RENDER_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "templateId": template_id,
        "path": spec["path"],
        "draftOnly": True,
        "requiresReview": True,
        "freezeBlocked": True,
        "qualityProfiles": list(spec["qualityProfiles"]),
        "declaredPlaceholders": list(spec["placeholders"]),
        "substitutedPlaceholders": sorted(values),
        "content": content,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "renderDigest": canonical_digest(body)}


def require_task_template_validation_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("task-template-validation-failed", "task template validation failed", {"validation": validation})
    return validation


def _template_record(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "templateId": spec["templateId"],
        "title": spec["title"],
        "path": spec["path"],
        "taskShape": spec["taskShape"],
        "draftOnly": True,
        "requiresReview": True,
        "freezeBlocked": True,
        "qualityProfiles": list(spec["qualityProfiles"]),
        "placeholders": list(spec["placeholders"]),
        "requiredMarkers": list(_REQUIRED_MARKERS),
        "runtimeDefaultsEmbedded": False,
        "providerSpecificCoreDependency": False,
    }


def _validate_template_record(project_root: Path, record: dict[str, Any], *, index: int) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    template_id = record.get("templateId")
    if not isinstance(template_id, str) or not template_id:
        blockers.append({"code": "task-template-id-invalid", "index": index})
    elif template_id not in {item["templateId"] for item in _TEMPLATE_SPECS}:
        blockers.append({"code": "task-template-id-unknown", "templateId": template_id})
    for key in ("draftOnly", "requiresReview", "freezeBlocked"):
        if record.get(key) is not True:
            blockers.append({"code": "task-template-gate-missing", "templateId": template_id, "field": key})
    if record.get("runtimeDefaultsEmbedded") is not False:
        blockers.append({"code": "task-template-runtime-defaults-embedded", "templateId": template_id})
    if record.get("providerSpecificCoreDependency") is not False:
        blockers.append({"code": "task-template-provider-core-dependency", "templateId": template_id})
    path_value = record.get("path")
    if not isinstance(path_value, str) or not path_value.startswith("templates/tasks/"):
        blockers.append({"code": "task-template-path-invalid", "templateId": template_id, "path": path_value})
    else:
        path = project_root / path_value
        if not path.is_file():
            blockers.append({"code": "task-template-file-missing", "templateId": template_id, "path": path_value})
        elif path.stat().st_size > MAX_TEMPLATE_BYTES:
            blockers.append({"code": "task-template-file-too-large", "templateId": template_id, "path": path_value})
        else:
            blockers.extend(_template_text_blockers(path.read_text(encoding="utf-8"), template_id=template_id))
    return {"templateId": template_id, "path": path_value, "status": "PASS" if not blockers else "FAIL", "blockers": blockers}


def _template_text_blockers(text: str, *, template_id: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for marker in _REQUIRED_MARKERS:
        if marker not in text:
            blockers.append({"code": "task-template-required-marker-missing", "templateId": template_id, "marker": marker})
    for marker in _FORBIDDEN_MARKERS:
        if marker in text:
            blockers.append({"code": "task-template-forbidden-marker", "templateId": template_id, "marker": marker})
    if template_id == "bugfix" and "Quality profile: bug-forensics optional" not in text:
        blockers.append({"code": "task-template-bugfix-profile-missing", "templateId": template_id})
    return blockers


def _validate_variables(spec: dict[str, Any], variables: dict[str, str]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(variables, dict):
        return [{"code": "task-template-variables-invalid"}]
    allowed = set(spec["placeholders"])
    for key, value in variables.items():
        if key not in allowed:
            blockers.append({"code": "task-template-variable-unknown", "key": key})
        if not isinstance(value, str):
            blockers.append({"code": "task-template-variable-not-string", "key": key})
        elif len(value) > MAX_VARIABLE_CHARS:
            blockers.append({"code": "task-template-variable-too-large", "key": key})
    return blockers


def _template_spec(template_id: str) -> dict[str, Any]:
    for spec in _TEMPLATE_SPECS:
        if spec["templateId"] == template_id:
            return spec
    raise LifecycleError("task-template-id-unknown", "task template id is unknown", {"templateId": template_id})


def _without_digest(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return {item_key: value for item_key, value in payload.items() if item_key != key}
