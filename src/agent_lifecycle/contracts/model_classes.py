"""Shared provider-neutral model classes used by contracts and routing."""

ALLOWED_MODEL_CLASSES = {
    "no-model",
    "budget",
    "local-compact",
    "standard-code",
    "local-standard-code",
    "strong-reasoning",
    "local-strong-review",
    "specialist-review",
}

LOCAL_MODEL_CLASSES = {"local-compact", "local-standard-code", "local-strong-review"}

CRITICAL_REVIEW_CLASSES = {"strong-reasoning", "local-strong-review", "specialist-review"}
