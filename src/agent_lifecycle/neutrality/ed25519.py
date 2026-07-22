"""Small pure-Python Ed25519 implementation for local portability.

The code follows the formulas from RFC 8032 and intentionally exposes only the
operations required by the lifecycle receipts.
"""

from __future__ import annotations

import hashlib

P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
I = pow(2, (P - 1) // 4, P)


def _x_recover(y: int) -> int:
    xx = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = (x * I) % P
    if x % 2 != 0:
        x = P - x
    return x


B = (_x_recover(4 * pow(5, P - 2, P) % P), 4 * pow(5, P - 2, P) % P)


def _is_on_curve(point: tuple[int, int]) -> bool:
    x, y = point
    return (-x * x + y * y - 1 - D * x * x * y * y) % P == 0


def _point_add(left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = left
    x2, y2 = right
    denominator = pow(1 + D * x1 * x2 * y1 * y2, P - 2, P)
    x3 = (x1 * y2 + x2 * y1) * denominator % P
    denominator = pow(1 - D * x1 * x2 * y1 * y2, P - 2, P)
    y3 = (y1 * y2 + x1 * x2) * denominator % P
    return x3, y3


def _scalar_mult(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    if scalar == 0:
        return 0, 1
    half = _scalar_mult(point, scalar // 2)
    doubled = _point_add(half, half)
    if scalar & 1:
        return _point_add(doubled, point)
    return doubled


def _encode_int(value: int) -> bytes:
    return value.to_bytes(32, "little")


def _encode_point(point: tuple[int, int]) -> bytes:
    x, y = point
    encoded = bytearray(_encode_int(y))
    encoded[31] |= (x & 1) << 7
    return bytes(encoded)


def _decode_point(data: bytes) -> tuple[int, int]:
    if len(data) != 32:
        raise ValueError("encoded point must be 32 bytes")
    y = int.from_bytes(data, "little") & ((1 << 255) - 1)
    x = _x_recover(y)
    if (x & 1) != (data[31] >> 7):
        x = P - x
    point = (x, y)
    if not _is_on_curve(point):
        raise ValueError("decoded point is not on curve")
    return point


def _hint(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _secret_scalar(seed: bytes) -> tuple[int, bytes]:
    if len(seed) != 32:
        raise ValueError("Ed25519 seed must be 32 bytes")
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def publickey_from_seed(seed: bytes) -> bytes:
    scalar, _prefix = _secret_scalar(seed)
    return _encode_point(_scalar_mult(B, scalar))


def sign(seed: bytes, message: bytes) -> bytes:
    scalar, prefix = _secret_scalar(seed)
    public_key = publickey_from_seed(seed)
    r = _hint(prefix + message) % Q
    encoded_r = _encode_point(_scalar_mult(B, r))
    h = _hint(encoded_r + public_key + message) % Q
    s = (r + h * scalar) % Q
    return encoded_r + _encode_int(s)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        point_a = _decode_point(public_key)
        point_r = _decode_point(signature[:32])
    except ValueError:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= Q:
        return False
    h = _hint(signature[:32] + public_key + message) % Q
    return _scalar_mult(B, s) == _point_add(point_r, _scalar_mult(point_a, h))


def fingerprint(public_key: bytes) -> str:
    return "ed25519:" + hashlib.sha256(public_key).hexdigest()
