"""Display prefixes never replace full SHA-256 identities."""

from __future__ import annotations

from agent_lifecycle.contracts.errors import LifecycleError

MAX_DISPLAY_IDENTITIES = 10_000


def digest_display_prefixes(digests: list[str], *, minimum_length: int = 12) -> dict[str, str]:
    """Expand colliding prefixes within this rendered set, deterministically."""
    if type(minimum_length) is not int or not 4 <= minimum_length <= 64:
        raise LifecycleError("display-prefix-length-invalid", "Display prefix length must be between 4 and 64")
    if not isinstance(digests, list) or len(digests) > MAX_DISPLAY_IDENTITIES:
        raise LifecycleError("display-identity-limit", "Display identity collection exceeds its limit")
    for value in digests:
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise LifecycleError("display-digest-invalid", "Display requires complete lowercase SHA-256 identities")
    unique = sorted(set(digests))
    result = {}
    for index, value in enumerate(unique):
        length = minimum_length
        for neighbor in unique[max(0, index - 1) : index] + unique[index + 1 : index + 2]:
            length = max(length, _common_prefix_length(value, neighbor) + 1)
        result[value] = value[:length]
    return result


def _common_prefix_length(first: str, second: str) -> int:
    for index, (left, right) in enumerate(zip(first, second, strict=True)):
        if left != right:
            return index
    return len(first)
