"""Build and validate the portable Agent Plugins projection for ALK."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SPEC_VERSION = "1.0.0"
SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
SCHEMA_PATH = Path("schemas/agent-plugins/1.0.0/plugin.schema.json")
PROVENANCE_PATH = Path("schemas/agent-plugins/1.0.0/provenance.json")
EXPECTED_SKILLS = (
    "agent-first-planning",
    "agent-plan-to-workers",
    "agent-workflow-orchestrator",
    "audit-agent-plan",
    "audit-plan-implementation",
    "bug-forensics",
    "issue-to-spec",
)
MAX_SKILL_COUNT = 32
MAX_SKILL_BYTES = 512 * 1024
MAX_PACKAGE_BYTES = 4 * 1024 * 1024
PLUGIN_NAME = "agent-lifecycle-kit"
PLUGIN_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
PLUGIN_NAME_PATTERN = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
ALLOWED_MANIFEST_FIELDS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}
FORBIDDEN_PACKAGE_ROOTS = {
    ".agents",
    ".alk",
    ".claude",
    ".codex",
    ".cursor",
    ".git",
    "adapters",
    "mcp.json",
    "src",
    "tasks",
    "work",
}
FORBIDDEN_FILE_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "secrets.json",
}


def build_plugin_manifest(version: str) -> dict[str, Any]:
    """Return the portable manifest without client-specific extensions."""
    _require_version(version)
    return {
        "$schema": SCHEMA_ID,
        "name": PLUGIN_NAME,
        "version": version,
        "description": "Provider-neutral lifecycle skills for planning, execution, validation and proof.",
        "author": {"name": "Agent Lifecycle Kit contributors"},
        "homepage": "https://github.com/avksp/agent-lifecycle-kit",
        "repository": "https://github.com/avksp/agent-lifecycle-kit",
        "license": "Apache-2.0",
        "keywords": ["agent-lifecycle", "agent-workflows", "coding-agents", "sdd"],
    }


def build_package(
    *,
    root: Path,
    version: str,
    output: Path,
    archive: Path | None = None,
) -> dict[str, Any]:
    """Build a fresh package and optionally a deterministic release archive."""
    _require_version(version)
    source_root = root / "skills"
    source_result = validate_skill_source(source_root)
    if source_result["status"] != "PASS":
        raise ValueError(json.dumps(source_result, sort_keys=True))
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    if archive is not None and archive.exists():
        raise FileExistsError(f"archive already exists: {archive}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True)
    _write_json(output / "plugin.json", build_plugin_manifest(version))
    target_skills = output / "skills"
    target_skills.mkdir()
    for skill_name in EXPECTED_SKILLS:
        _copy_tree_without_links(source_root / skill_name, target_skills / skill_name)

    package_result = validate_package(output, expected_version=version)
    if package_result["status"] != "PASS":
        raise ValueError(json.dumps(package_result, sort_keys=True))
    archive_result = None
    if archive is not None:
        build_archive(output, archive)
        archive_result = validate_archive(archive, package_root=output, expected_version=version)
        if archive_result["status"] != "PASS":
            raise ValueError(json.dumps(archive_result, sort_keys=True))
    return {
        "schemaVersion": "agent-plugin-build-evidence.v1",
        "status": "PASS",
        "package": package_result,
        "archive": archive_result,
        "productionPromotionClaimed": False,
    }


def validate_skill_source(source_root: Path) -> dict[str, Any]:
    """Validate the repository skill tree before copying it."""
    blockers: list[dict[str, Any]] = []
    if not _is_directory(source_root):
        blockers.append(_issue("skills-source-missing", source_root.as_posix()))
        return _validation("agent-plugin-skills-validation.v1", blockers, skills=[])
    children = sorted(source_root.iterdir(), key=lambda item: item.name)
    names = [child.name for child in children]
    if names != list(EXPECTED_SKILLS):
        blockers.append(_issue("skills-source-set-mismatch", source_root.as_posix(), expected=list(EXPECTED_SKILLS), actual=names))
    for child in children:
        if child.name not in EXPECTED_SKILLS:
            continue
        if not _is_directory(child):
            blockers.append(_issue("skill-directory-invalid", child.relative_to(source_root).as_posix()))
            continue
        blockers.extend(_validate_tree(child, source_root))
        skill_file = child / "SKILL.md"
        if not _is_regular_file(skill_file):
            blockers.append(_issue("skill-file-invalid", skill_file.relative_to(source_root).as_posix()))
        elif skill_file.stat().st_size > MAX_SKILL_BYTES:
            blockers.append(_issue("skill-size-limit", skill_file.relative_to(source_root).as_posix(), limit=MAX_SKILL_BYTES))
    return _validation("agent-plugin-skills-validation.v1", blockers, skills=names)


def validate_package(package_root: Path, *, expected_version: str | None = None) -> dict[str, Any]:
    """Validate a generated package using only local deterministic rules."""
    blockers: list[dict[str, Any]] = []
    if not _is_directory(package_root):
        return _validation("agent-plugin-package-validation.v1", [_issue("package-root-invalid", package_root.as_posix())])
    blockers.extend(_validate_tree(package_root, package_root))
    root_entries = sorted(item.name for item in package_root.iterdir())
    if root_entries != ["plugin.json", "skills"]:
        blockers.append(_issue("portable-root-mismatch", package_root.as_posix(), expected=["plugin.json", "skills"], actual=root_entries))

    manifest_path = package_root / "plugin.json"
    manifest: dict[str, Any] | None = None
    if _is_regular_file(manifest_path):
        try:
            manifest = _read_object(manifest_path)
            blockers.extend(validate_manifest(manifest, expected_version=expected_version)["blockers"])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blockers.append(_issue("plugin-manifest-invalid-json", manifest_path.as_posix(), error=str(exc)))
    else:
        blockers.append(_issue("plugin-manifest-missing", "plugin.json"))

    skills_root = package_root / "skills"
    skill_names: list[str] = []
    if not _is_directory(skills_root):
        blockers.append(_issue("skills-root-invalid", "skills"))
    else:
        children = sorted(skills_root.iterdir(), key=lambda item: item.name)
        skill_names = [child.name for child in children]
        if skill_names != list(EXPECTED_SKILLS):
            blockers.append(_issue("portable-skill-set-mismatch", "skills", expected=list(EXPECTED_SKILLS), actual=skill_names))
        if len(children) > MAX_SKILL_COUNT:
            blockers.append(_issue("skill-count-limit", "skills", limit=MAX_SKILL_COUNT))
        for child in children:
            if not _is_directory(child):
                blockers.append(_issue("portable-skill-directory-invalid", f"skills/{child.name}"))
                continue
            skill_file = child / "SKILL.md"
            if not _is_regular_file(skill_file):
                blockers.append(_issue("portable-skill-file-invalid", f"skills/{child.name}/SKILL.md"))
            elif skill_file.stat().st_size > MAX_SKILL_BYTES:
                blockers.append(_issue("skill-size-limit", f"skills/{child.name}/SKILL.md", limit=MAX_SKILL_BYTES))

    files = _regular_files(package_root)
    total_bytes = sum(path.stat().st_size for path in files)
    if total_bytes > MAX_PACKAGE_BYTES:
        blockers.append(_issue("package-size-limit", package_root.as_posix(), limit=MAX_PACKAGE_BYTES, actual=total_bytes))
    if manifest is not None and manifest.get("name") != PLUGIN_NAME:
        blockers.append(_issue("plugin-name-mismatch", "plugin.json", expected=PLUGIN_NAME, actual=manifest.get("name")))
    return _validation(
        "agent-plugin-package-validation.v1",
        blockers,
        packagePath=package_root.as_posix(),
        files=[path.relative_to(package_root).as_posix() for path in files],
        skillNames=skill_names,
        totalBytes=total_bytes,
        productionPromotionClaimed=False,
    )


def validate_manifest(manifest: dict[str, Any], *, expected_version: str | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(manifest, dict):
        return _validation("agent-plugin-manifest-validation.v1", [_issue("manifest-not-object", "plugin.json")])
    unknown = sorted(set(manifest) - ALLOWED_MANIFEST_FIELDS)
    if unknown:
        blockers.append(_issue("manifest-unknown-fields", "plugin.json", fields=unknown))
    if manifest.get("$schema") != SCHEMA_ID:
        blockers.append(_issue("manifest-schema-mismatch", "plugin.json", expected=SCHEMA_ID, actual=manifest.get("$schema")))
    name = manifest.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 64 or not PLUGIN_NAME_PATTERN.fullmatch(name):
        blockers.append(_issue("manifest-name-invalid", "plugin.json"))
    version = manifest.get("version")
    if version is not None and (not isinstance(version, str) or not PLUGIN_VERSION_PATTERN.fullmatch(version)):
        blockers.append(_issue("manifest-version-invalid", "plugin.json"))
    if expected_version is not None and version != expected_version:
        blockers.append(_issue("manifest-version-mismatch", "plugin.json", expected=expected_version, actual=version))
    for field in ("description", "homepage", "repository", "license"):
        if field in manifest and not isinstance(manifest[field], str):
            blockers.append(_issue("manifest-field-invalid", f"plugin.json:{field}"))
    if "keywords" in manifest and (
        not isinstance(manifest["keywords"], list)
        or any(not isinstance(value, str) for value in manifest["keywords"])
    ):
        blockers.append(_issue("manifest-keywords-invalid", "plugin.json"))
    author = manifest.get("author")
    if author is not None and (
        not isinstance(author, dict)
        or set(author) - {"name", "email", "url"}
        or any(not isinstance(value, str) for value in author.values())
    ):
        blockers.append(_issue("manifest-author-invalid", "plugin.json"))
    extensions = manifest.get("extensions")
    if extensions is not None and (
        not isinstance(extensions, dict)
        or any(not isinstance(value, dict) for value in extensions.values())
    ):
        blockers.append(_issue("manifest-extensions-invalid", "plugin.json"))
    return _validation("agent-plugin-manifest-validation.v1", blockers, schemaId=SCHEMA_ID, name=name, version=version)


def build_archive(package_root: Path, archive_path: Path) -> None:
    """Write a deterministic archive containing only regular package files."""
    if not _is_directory(package_root):
        raise ValueError(f"package root is not a directory: {package_root}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _regular_files(package_root):
            relative = path.relative_to(package_root).as_posix()
            _require_safe_archive_name(relative)
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())


def validate_archive(
    archive_path: Path,
    *,
    package_root: Path | None = None,
    expected_version: str | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not _is_regular_file(archive_path):
        return _validation("agent-plugin-archive-validation.v1", [_issue("archive-invalid", archive_path.as_posix())])
    if archive_path.stat().st_size > MAX_PACKAGE_BYTES:
        blockers.append(_issue("archive-size-limit", archive_path.as_posix(), limit=MAX_PACKAGE_BYTES))
    names: list[str] = []
    content: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                name = info.filename
                try:
                    _require_safe_archive_name(name)
                except ValueError as exc:
                    blockers.append(_issue("archive-path-invalid", name, error=str(exc)))
                    continue
                if name in content:
                    blockers.append(_issue("archive-duplicate-path", name))
                    continue
                if stat.S_ISLNK(info.external_attr >> 16):
                    blockers.append(_issue("archive-symlink-rejected", name))
                    continue
                if info.is_dir():
                    blockers.append(_issue("archive-directory-entry-rejected", name))
                    continue
                names.append(name)
                content[name] = archive.read(info)
    except (OSError, zipfile.BadZipFile) as exc:
        blockers.append(_issue("archive-unreadable", archive_path.as_posix(), error=str(exc)))

    if "mcp.json" in content:
        blockers.append(_issue("portable-mcp-rejected", "mcp.json"))
    if "plugin.json" in content:
        try:
            manifest = json.loads(content["plugin.json"].decode("utf-8"))
            blockers.extend(validate_manifest(manifest, expected_version=expected_version)["blockers"])
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            blockers.append(_issue("archive-manifest-invalid", "plugin.json", error=str(exc)))
    else:
        blockers.append(_issue("archive-manifest-missing", "plugin.json"))
    expected_files = None
    if package_root is not None:
        expected_files = {path.relative_to(package_root).as_posix(): path.read_bytes() for path in _regular_files(package_root)}
        if set(content) != set(expected_files):
            blockers.append(_issue("archive-content-mismatch", archive_path.as_posix(), expected=sorted(expected_files), actual=sorted(content)))
        for name, data in expected_files.items():
            if content.get(name) != data:
                blockers.append(_issue("archive-file-mismatch", name))
    return _validation(
        "agent-plugin-archive-validation.v1",
        blockers,
        archivePath=archive_path.as_posix(),
        files=sorted(names),
        bytes=archive_path.stat().st_size,
        productionPromotionClaimed=False,
    )


def provenance_for_schema(root: Path) -> dict[str, Any]:
    schema_path = root / SCHEMA_PATH
    provenance_path = root / PROVENANCE_PATH
    schema_digest = _sha256_file(schema_path)
    provenance = _read_object(provenance_path)
    blockers = []
    if provenance.get("canonicalUrl") != SCHEMA_ID:
        blockers.append(_issue("schema-provenance-url-mismatch", PROVENANCE_PATH.as_posix()))
    if provenance.get("specificationVersion") != SPEC_VERSION:
        blockers.append(_issue("schema-provenance-version-mismatch", PROVENANCE_PATH.as_posix()))
    if provenance.get("sourceDigest") != schema_digest or provenance.get("localSchemaDigest") != schema_digest:
        blockers.append(_issue("schema-provenance-digest-mismatch", PROVENANCE_PATH.as_posix(), expected=schema_digest))
    return _validation("agent-plugin-schema-provenance-validation.v1", blockers, schemaDigest=schema_digest, provenancePath=PROVENANCE_PATH.as_posix())


def _validate_tree(path: Path, root: Path) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()
    if path.is_symlink():
        return [_issue("symlink-rejected", relative)]
    if path.is_dir():
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            blockers.extend(_validate_tree(child, root))
        return blockers
    if not _is_regular_file(path):
        blockers.append(_issue("non-regular-file-rejected", relative))
    if path.name in FORBIDDEN_FILE_NAMES or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        blockers.append(_issue("secret-like-file-rejected", relative))
    if any(part in FORBIDDEN_PACKAGE_ROOTS for part in Path(relative).parts):
        blockers.append(_issue("forbidden-component-rejected", relative))
    return blockers


def _copy_tree_without_links(source: Path, target: Path) -> None:
    if not _is_directory(source):
        raise ValueError(f"source is not a regular directory: {source}")
    target.mkdir(parents=True)
    for item in sorted(source.iterdir(), key=lambda child: child.name):
        if item.is_symlink():
            raise ValueError(f"symlink is not allowed: {item}")
        destination = target / item.name
        if item.is_dir():
            _copy_tree_without_links(item, destination)
        elif item.is_file():
            shutil.copyfile(item, destination)
        else:
            raise ValueError(f"non-regular source entry: {item}")


def _regular_files(root: Path) -> list[Path]:
    return sorted((item for item in root.rglob("*") if _is_regular_file(item)), key=lambda item: item.relative_to(root).as_posix())


def _is_directory(path: Path) -> bool:
    return path.exists() and not path.is_symlink() and path.is_dir()


def _is_regular_file(path: Path) -> bool:
    return path.exists() and not path.is_symlink() and path.is_file()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_version(version: str) -> None:
    if not isinstance(version, str) or not PLUGIN_VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"invalid plugin version: {version!r}")


def _require_safe_archive_name(name: str) -> None:
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or ".." in path.parts or any(part == "" for part in path.parts):
        raise ValueError("archive path must be a non-empty relative POSIX path without traversal")


def _issue(code: str, path: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "path": path, **details}


def _validation(schema_version: str, blockers: list[dict[str, Any]], **details: Any) -> dict[str, Any]:
    return {"schemaVersion": schema_version, "status": "PASS" if not blockers else "FAIL", "blockers": blockers, **details}
