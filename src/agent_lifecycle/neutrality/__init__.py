"""Neutrality scanner and detached receipt primitives."""

from .authority import AuthorityBundle, load_authority_bundle
from .scanner import (
    LEGACY_NEUTRALITY_SCOPES,
    NEUTRALITY_SCOPE_CHOICES,
    TRACKED_RELEASE_SCOPE,
    NeutralityFinding,
    NeutralityReport,
    scan_repository,
)

__all__ = [
    "AuthorityBundle",
    "LEGACY_NEUTRALITY_SCOPES",
    "NEUTRALITY_SCOPE_CHOICES",
    "NeutralityFinding",
    "NeutralityReport",
    "TRACKED_RELEASE_SCOPE",
    "load_authority_bundle",
    "scan_repository",
]
