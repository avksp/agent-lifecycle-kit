"""Small pure-Python Ed25519 implementation for local portability.

The code follows the formulas from RFC 8032 and intentionally exposes only the
operations required by the lifecycle receipts.
"""

from __future__ import annotations

import hashlib

P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _x_recover(y: int) -> int:
    xx = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = (x * SQRT_M1) % P
    if x % 2 != 0:
        x = P - x
    return x


_BASE_Y = 4 * pow(5, P - 2, P) % P
B = (_x_recover(_BASE_Y), _BASE_Y)

# Extended Edwards coordinates keep X/Z and Y/Z while retaining XY/Z in T.
# The representation removes field inversions from the scalar-multiplication
# loop; conversion back to affine coordinates happens only when encoding.
ExtendedPoint = tuple[int, int, int, int]
_IDENTITY: ExtendedPoint = (0, 1, 1, 0)


def _extended_from_affine(point: tuple[int, int]) -> ExtendedPoint:
    x, y = point
    return x, y, 1, (x * y) % P


def _is_on_curve(point: tuple[int, int]) -> bool:
    x, y = point
    return (-x * x + y * y - 1 - D * x * x * y * y) % P == 0


def _extended_add(left: ExtendedPoint, right: ExtendedPoint) -> ExtendedPoint:
    x1, y1, z1, t1 = left
    x2, y2, z2, t2 = right
    a = ((y1 - x1) * (y2 - x2)) % P
    b = ((y1 + x1) * (y2 + x2)) % P
    c = (2 * D * t1 * t2) % P
    d = (2 * z1 * z2) % P
    e = (b - a) % P
    f = (d - c) % P
    g = (d + c) % P
    h = (b + a) % P
    return (e * f) % P, (g * h) % P, (f * g) % P, (e * h) % P


def _extended_double(point: ExtendedPoint) -> ExtendedPoint:
    x1, y1, z1, _t1 = point
    a = (x1 * x1) % P
    b = (y1 * y1) % P
    c = (2 * z1 * z1) % P
    d = (-a) % P
    e = ((x1 + y1) * (x1 + y1) - a - b) % P
    g = (d + b) % P
    f = (g - c) % P
    h = (d - b) % P
    return (e * f) % P, (g * h) % P, (f * g) % P, (e * h) % P


def _scalar_mult(point: tuple[int, int], scalar: int) -> ExtendedPoint:
    result = _IDENTITY
    addend = _extended_from_affine(point)
    while scalar > 0:
        if scalar & 1:
            result = _extended_add(result, addend)
        addend = _extended_double(addend)
        scalar >>= 1
    return result


def _encode_int(value: int) -> bytes:
    return value.to_bytes(32, "little")


def _encode_point(point: ExtendedPoint) -> bytes:
    x_projective, y_projective, z, _t = point
    z_inverse = pow(z, P - 2, P)
    x = (x_projective * z_inverse) % P
    y = (y_projective * z_inverse) % P
    encoded = bytearray(_encode_int(y))
    encoded[31] |= (x & 1) << 7
    return bytes(encoded)


def _decode_point(data: bytes) -> tuple[int, int]:
    if len(data) != 32:
        raise ValueError("encoded point must be 32 bytes")
    encoded = int.from_bytes(data, "little")
    sign_bit = encoded >> 255
    y = encoded & ((1 << 255) - 1)
    if y >= P:
        raise ValueError("encoded point is not canonical")
    x = _x_recover(y)
    if (x & 1) != sign_bit:
        x = P - x
    if x >= P or (x == 0 and sign_bit != 0):
        raise ValueError("encoded point sign is not canonical")
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
    left = _scalar_mult(B, s)
    right = _extended_add(_extended_from_affine(point_r), _scalar_mult(point_a, h))
    return _encode_point(left) == _encode_point(right)


def fingerprint(public_key: bytes) -> str:
    return "ed25519:" + hashlib.sha256(public_key).hexdigest()
