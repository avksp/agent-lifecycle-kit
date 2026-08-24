"""Project-facing facade for the optional domain-language contracts."""

from __future__ import annotations

from agent_lifecycle.contracts.domain_language import (
    build_domain_language_delta,
    domain_language_digest,
    language_terms,
    load_domain_language,
    validate_domain_language,
)

__all__ = [
    "build_domain_language_delta",
    "domain_language_digest",
    "language_terms",
    "load_domain_language",
    "validate_domain_language",
]
